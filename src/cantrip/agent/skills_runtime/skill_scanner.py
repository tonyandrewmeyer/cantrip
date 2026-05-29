"""Static scanner for ``SKILL.md`` files.

Mirrors the checks documented in the ``skill-scanner`` skill:
prompt-injection phrases, unscoped authority claims, description
drift, body length, missing sections, bare external URLs, user-like
text, and frontmatter validity.  Used by the CI test in
``tests/unit/test_skill_scanner.py`` to keep bundled skills clean.
"""

import dataclasses
import pathlib
import re

import yaml

# Frontmatter delimiter matches ``SkillsIndex._parse_frontmatter``.
_FRONTMATTER_DELIMITER = "---"

# Severity labels.
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"


@dataclasses.dataclass(frozen=True)
class Finding:
    """A single scanner finding."""

    skill: str
    severity: str
    code: str
    message: str
    line: int | None = None


# Prompt-injection phrasing — fairly conservative list; adding false
# positives is worse than missing a novel phrasing, since the scanner
# runs in CI.
_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?previous\s+instructions?\b", re.IGNORECASE),
    re.compile(
        r"\bdisregard\s+(?:the\s+|your\s+)?(?:system|previous)\s+(?:prompt|instructions?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\byou\s+are\s+(?:now\s+|actually\s+)?an?\s+[\w\- ]{1,40}?(?:assistant|agent|model)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bforget\s+(?:everything|what\s+you\s+were\s+told)\b", re.IGNORECASE),
    re.compile(r"^(?:new\s+instructions?|new\s+task):", re.IGNORECASE | re.MULTILINE),
)

# Bare external URLs outside a recognised references-style section trigger a
# MEDIUM finding; the regex itself just spots candidate URLs.
_URL_RE = re.compile(r"https?://\S+")

# Sections we treat as safe homes for external URLs.
_REFERENCE_SECTION_HEADINGS = {
    "source material",
    "references",
    "further reading",
    "citations",
    "resources",
    "external links",
    "related docs",
    "links",
    "provenance",
}


def _strip_code_blocks(body: str) -> str:
    """Replace fenced code content and HTML-comment bodies with blank lines
    so body checks don't fire on example material that is clearly marked
    as example.

    Preserves line numbers so findings on the stripped body map back to
    the original line.  Fenced blocks opened by ``\u0060\u0060\u0060``
    and ``~~~`` are cleared, along with content between ``<!--`` and
    ``-->``.  Inline ``\u0060code\u0060`` spans are left alone — the
    false-positive risk from bare inline code is negligible.
    """
    lines = body.split("\n")
    in_fence = False
    in_html_comment = False
    out: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence:
            out.append("")
            continue
        if "<!--" in line and "-->" in line and line.index("<!--") < line.index("-->"):
            # Single-line comment — clear its content.
            out.append("")
            continue
        if "<!--" in line:
            in_html_comment = True
            out.append("")
            continue
        if "-->" in line:
            in_html_comment = False
            out.append("")
            continue
        if in_html_comment:
            out.append("")
            continue
        out.append(line)
    return "\n".join(out)


def _strip_frontmatter(raw: str) -> tuple[str, dict[str, object] | None, int]:
    """Return (body, frontmatter_mapping_or_none, body_line_offset).

    ``body_line_offset`` is the number of lines the frontmatter block
    occupies so we can report body findings with real line numbers.
    """
    lines = raw.split("\n")
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        return raw, None, 0

    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONTMATTER_DELIMITER:
            end = i
            break
    if end is None:
        return raw, None, 0

    frontmatter_text = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(frontmatter_text)
    except (yaml.YAMLError, RecursionError):
        data = None
    body = "\n".join(lines[end + 1 :])
    return body, data if isinstance(data, dict) else None, end + 1


def _enumerate_headings(body: str) -> list[tuple[int, str]]:
    """Return ``[(line_number, heading_text_lowercase), ...]`` for ATX headings."""
    headings: list[tuple[int, str]] = []
    for idx, line in enumerate(body.splitlines(), start=1):
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            headings.append((idx, match.group(1).strip().lower()))
    return headings


def _section_at(lineno: int, headings: list[tuple[int, str]]) -> str:
    """Return the lowercased heading text for the section containing *lineno*."""
    active = ""
    for hline, htext in headings:
        if hline <= lineno:
            active = htext
        else:
            break
    return active


def _check_frontmatter(
    skill_name: str,
    skill_path: pathlib.Path,
    frontmatter: dict[str, object] | None,
) -> list[Finding]:
    """HIGH findings for missing/invalid frontmatter."""
    findings: list[Finding] = []
    if frontmatter is None:
        findings.append(
            Finding(
                skill=skill_name,
                severity=SEVERITY_HIGH,
                code="frontmatter-missing",
                message=f"{skill_path}: no parseable YAML frontmatter",
            )
        )
        return findings

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not name:
        findings.append(
            Finding(
                skill=skill_name,
                severity=SEVERITY_HIGH,
                code="frontmatter-name-missing",
                message="frontmatter must set a non-empty ``name``",
            )
        )
    elif name != skill_name:
        findings.append(
            Finding(
                skill=skill_name,
                severity=SEVERITY_HIGH,
                code="frontmatter-name-mismatch",
                message=(
                    f"frontmatter ``name: {name}`` disagrees with directory ``{skill_name}``"
                ),
            )
        )
    if not isinstance(description, str) or not description:
        findings.append(
            Finding(
                skill=skill_name,
                severity=SEVERITY_HIGH,
                code="frontmatter-description-missing",
                message="frontmatter must set a non-empty ``description``",
            )
        )
    elif len(description) > 160:
        findings.append(
            Finding(
                skill=skill_name,
                severity=SEVERITY_MEDIUM,
                code="description-too-long",
                message=(
                    f"description is {len(description)} characters; aim for ≤120 "
                    "to keep the index scannable"
                ),
            )
        )
    return findings


def _check_injection(skill_name: str, body: str, offset: int) -> list[Finding]:
    """HIGH findings for prompt-injection phrasing.

    Content inside fenced code blocks is stripped before scanning —
    skills are expected to document the phrases they detect by
    example, and those examples belong in a fence.
    """
    findings: list[Finding] = []
    scanned = _strip_code_blocks(body)
    for pattern in _INJECTION_PATTERNS:
        for match in pattern.finditer(scanned):
            line = scanned.count("\n", 0, match.start()) + 1 + offset
            findings.append(
                Finding(
                    skill=skill_name,
                    severity=SEVERITY_HIGH,
                    code="prompt-injection",
                    message=f"prompt-injection phrase at line {line}: {match.group(0)!r}",
                    line=line,
                )
            )
    return findings


def _check_length(skill_name: str, body: str) -> list[Finding]:
    """Body-size findings."""
    findings: list[Finding] = []
    lines = body.count("\n") + 1
    if lines > 1200:
        severity = SEVERITY_HIGH
    elif lines > 800:
        severity = SEVERITY_MEDIUM
    elif lines > 500:
        severity = SEVERITY_LOW
    else:
        return findings
    findings.append(
        Finding(
            skill=skill_name,
            severity=severity,
            code="body-too-long",
            message=(
                f"body is {lines} lines; consider splitting along verb or sub-domain boundaries"
            ),
        )
    )
    return findings


def _check_required_sections(skill_name: str, body: str) -> list[Finding]:
    """LOW findings when the body lacks the structural sections.

    These are style recommendations from ``skill-writer``; legacy
    skills predate the convention and still work, so we flag but
    don't block.
    """
    findings: list[Finding] = []
    lowered = body.lower()
    if "## when to use" not in lowered and "## how to use" not in lowered:
        findings.append(
            Finding(
                skill=skill_name,
                severity=SEVERITY_LOW,
                code="missing-when-to-use",
                message="body is missing a ``## When to use`` (or equivalent) section",
            )
        )
    negative_markers = (
        "## when to skip",
        "## when not to use",
        "## what this skill is not",
        "## what this skill is *not*",
    )
    if not any(marker in lowered for marker in negative_markers):
        findings.append(
            Finding(
                skill=skill_name,
                severity=SEVERITY_LOW,
                code="missing-scope-limit",
                message=(
                    "body is missing a negative-case section (``## When to skip`` / "
                    "``## What this skill is not``)"
                ),
            )
        )
    return findings


def _check_bare_urls(skill_name: str, body: str, offset: int) -> list[Finding]:
    """MEDIUM findings for URLs outside a references-style section.

    URLs inside fenced code blocks (typically example commands or
    placeholder endpoints like ``http://localhost:8080``) are
    exempted — those are clearly example material, not authoritative
    external references.  ``localhost`` URLs outside fences are also
    exempted for the same reason.
    """
    findings: list[Finding] = []
    scanned = _strip_code_blocks(body)
    headings = _enumerate_headings(body)
    for match in _URL_RE.finditer(scanned):
        url = match.group(0)
        if "localhost" in url or "127.0.0.1" in url:
            continue
        line = scanned.count("\n", 0, match.start()) + 1
        section = _section_at(line, headings)
        if section in _REFERENCE_SECTION_HEADINGS:
            continue
        findings.append(
            Finding(
                skill=skill_name,
                severity=SEVERITY_MEDIUM,
                code="bare-external-url",
                message=(
                    f"external URL on line {line + offset} outside a references section: " + url
                ),
                line=line + offset,
            )
        )
    return findings


def scan_skill(skill_dir: pathlib.Path) -> list[Finding]:
    """Scan a single skill directory and return findings.

    ``skill_dir`` is the directory containing ``SKILL.md``; the scanner
    takes the directory name as the expected ``name`` field.
    """
    skill_name = skill_dir.name
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return [
            Finding(
                skill=skill_name,
                severity=SEVERITY_HIGH,
                code="skill-md-missing",
                message=f"{skill_dir}: no SKILL.md",
            )
        ]

    raw = skill_file.read_text()
    body, frontmatter, offset = _strip_frontmatter(raw)

    findings: list[Finding] = []
    findings.extend(_check_frontmatter(skill_name, skill_file, frontmatter))
    findings.extend(_check_injection(skill_name, body, offset))
    findings.extend(_check_length(skill_name, body))
    findings.extend(_check_required_sections(skill_name, body))
    findings.extend(_check_bare_urls(skill_name, body, offset))
    return findings


def scan_all(skills_root: pathlib.Path) -> list[Finding]:
    """Scan every skill directory under *skills_root*."""
    if not skills_root.is_dir():
        return []
    findings: list[Finding] = []
    for child in sorted(skills_root.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            findings.extend(scan_skill(child))
    return findings


def format_findings(findings: list[Finding]) -> str:
    """Render a list of findings as a human-readable block."""
    if not findings:
        return "[skill-scanner] no findings"
    by_skill: dict[str, list[Finding]] = {}
    for f in findings:
        by_skill.setdefault(f.skill, []).append(f)
    blocks: list[str] = []
    for skill, group in sorted(by_skill.items()):
        counts = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 0, SEVERITY_LOW: 0}
        for f in group:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        header = (
            f"[skill-scanner] {skill}: {counts[SEVERITY_HIGH]} HIGH, "
            f"{counts[SEVERITY_MEDIUM]} MEDIUM, {counts[SEVERITY_LOW]} LOW"
        )
        lines = [header]
        for f in sorted(group, key=lambda x: (x.severity, x.code)):
            lines.append(f"  {f.severity}: {f.code} — {f.message}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
