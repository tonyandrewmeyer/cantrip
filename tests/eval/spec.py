"""Evaluation spec and rubric data structures.

An evaluation spec defines *what* Cantrip should build (the prompt and
requirements) and *how* to judge the result (the rubric).  Gold-standard
implementations live alongside the spec as complete charm directories that
should score perfectly against the rubric.
"""

import dataclasses
import enum
import pathlib

import yaml


class CharmPath(enum.Enum):
    """Which of the three charm-building paths this spec exercises."""

    TWELVE_FACTOR = "twelve-factor"
    CUSTOM = "custom"
    INFRASTRUCTURE = "infrastructure"


class Substrate(enum.Enum):
    """Target substrate for the charm."""

    K8S = "k8s"
    MACHINE = "machine"


class Severity(enum.Enum):
    """How heavily a rubric criterion weighs on the final score."""

    CRITICAL = "critical"  # Must pass — failing zeroes the category.
    MAJOR = "major"  # Strong weight.
    MINOR = "minor"  # Nice-to-have.


@dataclasses.dataclass(frozen=True)
class Criterion:
    """A single rubric criterion.

    Each criterion is a yes/no check against the generated charm directory.
    The ``check`` field names a checker function in ``checks.py``; ``args``
    supplies keyword arguments.
    """

    name: str
    description: str
    category: str  # e.g. "structure", "metadata", "code", "testing", "cos"
    severity: Severity
    check: str  # Dotted name of the checker function.
    args: dict = dataclasses.field(default_factory=dict)
    points: int = 1


@dataclasses.dataclass(frozen=True)
class Rubric:
    """The full set of criteria for evaluating a generated charm."""

    criteria: tuple[Criterion, ...]

    @property
    def max_points(self) -> int:
        return sum(c.points for c in self.criteria)

    @property
    def categories(self) -> set[str]:
        return {c.category for c in self.criteria}


@dataclasses.dataclass(frozen=True)
class EvalSpec:
    """Everything needed to run and score one evaluation."""

    name: str  # Short identifier, e.g. "flask-bookmark".
    description: str  # Human-readable summary.
    charm_path_type: CharmPath
    substrate: Substrate
    prompt: str  # The opening message sent to Cantrip.
    follow_ups: tuple[str, ...] = ()  # Optional multi-turn messages.
    rubric: Rubric = dataclasses.field(default_factory=lambda: Rubric(()))
    gold_standards: tuple[str, ...] = ()  # Directory names under charms/<name>/.

    @classmethod
    def load(cls, spec_dir: pathlib.Path) -> "EvalSpec":
        """Load an evaluation spec from a directory.

        Expects ``spec.yaml`` in *spec_dir* plus zero or more gold-standard
        subdirectories.
        """
        spec_file = spec_dir / "spec.yaml"
        raw = yaml.safe_load(spec_file.read_text())

        criteria = []
        for entry in raw.get("rubric", []):
            criteria.append(
                Criterion(
                    name=entry["name"],
                    description=entry.get("description", ""),
                    category=entry["category"],
                    severity=Severity(entry.get("severity", "major")),
                    check=entry["check"],
                    args=entry.get("args", {}),
                    points=entry.get("points", 1),
                )
            )

        # Discover gold-standard directories (any subdir that isn't __pycache__).
        golds = sorted(
            d.name for d in spec_dir.iterdir() if d.is_dir() and not d.name.startswith(("_", "."))
        )

        return cls(
            name=raw["name"],
            description=raw["description"],
            charm_path_type=CharmPath(raw["charm_path"]),
            substrate=Substrate(raw["substrate"]),
            prompt=raw["prompt"],
            follow_ups=tuple(raw.get("follow_ups", [])),
            rubric=Rubric(tuple(criteria)),
            gold_standards=tuple(golds),
        )


@dataclasses.dataclass
class CriterionResult:
    """Result of evaluating a single criterion."""

    criterion: Criterion
    passed: bool
    detail: str = ""


@dataclasses.dataclass
class EvalResult:
    """Full result of evaluating a generated charm against a rubric."""

    spec_name: str
    provider: str
    model: str
    results: list[CriterionResult] = dataclasses.field(default_factory=list)

    @property
    def score(self) -> int:
        return sum(r.criterion.points for r in self.results if r.passed)

    @property
    def max_score(self) -> int:
        return sum(r.criterion.points for r in self.results)

    @property
    def percentage(self) -> float:
        if self.max_score == 0:
            return 0.0
        return (self.score / self.max_score) * 100

    @property
    def critical_failures(self) -> list[CriterionResult]:
        return [
            r for r in self.results if not r.passed and r.criterion.severity is Severity.CRITICAL
        ]

    def category_scores(self) -> dict[str, tuple[int, int]]:
        """Return {category: (earned, possible)} scores."""
        scores: dict[str, tuple[int, int]] = {}
        for r in self.results:
            earned, possible = scores.get(r.criterion.category, (0, 0))
            possible += r.criterion.points
            if r.passed:
                earned += r.criterion.points
            scores[r.criterion.category] = (earned, possible)
        return scores

    def summary(self) -> str:
        """Human-readable one-line summary."""
        crit = len(self.critical_failures)
        if crit:
            return f"{self.spec_name}: {self.percentage:.0f}% ({crit} CRITICAL failures)"
        return f"{self.spec_name}: {self.percentage:.0f}%"
