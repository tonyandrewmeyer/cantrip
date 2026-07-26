"""Jujuignore pattern matching.

Ported from charmcraft's jujuignore module.  Patterns follow gitignore-like
syntax: ``*`` matches within a directory, ``**`` matches across directories,
``!`` inverts, and a trailing ``/`` restricts to directories.
"""

import re

# Default patterns that Juju itself always applies.
DEFAULT_IGNORES = [
    ".git",
    ".svn",
    ".hg",
    ".bzr",
    ".tox",
    "/build/",
    "/revision",
    "/venv",
    ".jujuignore",
]


def _rstrip_unescaped(rule: str) -> str:
    """Remove trailing whitespace that isn't escaped."""
    i = len(rule) - 1
    last = len(rule)
    while i >= 0:
        if rule[i] in ("\n", "\r"):
            last = i
        elif rule[i] != " ":
            break
        elif i == 0 or rule[i - 1] != "\\":
            last = i
        i -= 1
    return rule[:last]


_UNESCAPES = {r"\!": "!", r"\ ": " ", r"\#": "#"}


def _unescape(rule: str) -> str:
    rule = rule.lstrip()
    rule = _rstrip_unescaped(rule)
    for old, new in _UNESCAPES.items():
        rule = rule.replace(old, new)
    return rule


def _rule_to_regex(rule: str) -> str:
    """Convert a jujuignore rule to a regex pattern."""
    i, n = 0, len(rule)
    res = ""
    while i < n:
        c = rule[i]
        i += 1
        if c == "*":
            if i < n and rule[i] == "*":
                i += 1
                res += ".*"
            else:
                res += "[^/]*"
        elif c == "?":
            res += "[^/]"
        elif c == "[":
            j = i
            if j < n and rule[j] == "!":
                j += 1
            if j < n and rule[j] == "]":
                j += 1
            while j < n and rule[j] != "]":
                j += 1
            if j >= n:
                res += "\\["
            else:
                stuff = rule[i:j]
                stuff = re.sub(r"([&~|])", r"\\\1", stuff)
                i = j + 1
                if stuff[0] == "!":
                    stuff = "^" + stuff[1:]
                elif stuff[0] == "[":
                    stuff = "\\" + stuff
                res = f"{res}[{stuff}]"
        elif c == "/":
            # ``/**/`` can match a single ``/``.
            if i < n and rule[i] == "*" and rule[i - 1 : i + 3] == "/**/":
                i += 3
                res += ".*/"
            else:
                res += "/"
        else:
            res += re.escape(c)
    res += r"\Z"
    return res


class _Matcher:
    """A compiled ignore rule."""

    __slots__ = ("compiled", "invert", "only_dirs")

    def __init__(self, *, invert: bool, only_dirs: bool, regex: str) -> None:
        self.invert = invert
        self.only_dirs = only_dirs
        self.compiled = re.compile(regex, re.DOTALL)

    def match(self, path: str, *, is_dir: bool) -> str:
        if self.only_dirs and not is_dir:
            return "keep"
        if self.compiled.match(path):
            return "forcekeep" if self.invert else "skip"
        return "keep"


class JujuIgnore:
    """Track a set of ignore patterns."""

    def __init__(self, patterns: list[str] | None = None) -> None:
        self._matchers: list[_Matcher] = []
        self.extend(DEFAULT_IGNORES)
        if patterns:
            self.extend(patterns)

    def extend(self, patterns: list[str]) -> None:
        """Add more patterns to the ignore list."""
        for rule in patterns:
            rule = rule.lstrip().rstrip("\r\n")
            if not rule or rule.startswith("#"):
                continue
            invert = False
            if rule.startswith("!"):
                invert = True
                rule = rule.lstrip("!")
            rule = _unescape(rule)
            only_dirs = False
            if rule.endswith("/"):
                only_dirs = True
                rule = rule.rstrip("/")
            if not rule.startswith("/"):
                rule = "**/" + rule
            regex = _rule_to_regex(rule)
            self._matchers.append(_Matcher(invert=invert, only_dirs=only_dirs, regex=regex))

    def match(self, path: str, *, is_dir: bool) -> bool:
        """Return True if *path* should be ignored."""
        if not path.startswith("/"):
            path = "/" + path
        keep = True
        for matcher in self._matchers:
            result = matcher.match(path, is_dir=is_dir)
            if result == "skip":
                keep = False
            elif result == "forcekeep":
                keep = True
                break
        return not keep

    @classmethod
    def from_file(cls, jujuignore_path: str) -> "JujuIgnore":
        """Load patterns from a ``.jujuignore`` file on top of the defaults."""
        import pathlib

        path = pathlib.Path(jujuignore_path)
        patterns: list[str] = []
        if path.exists():
            patterns = path.read_text(encoding="utf-8").splitlines()
        return cls(patterns)
