"""Load test generation tool — produces charm-specific load test scripts."""

from pathlib import Path
from typing import Any

import yaml

from cantrip.agent.tools.base import Tool, ToolResult


def generate_load_test(
    charm_name: str,
    metadata: dict[str, Any],
) -> dict[str, str]:
    """Generate load test files from charm metadata.

    Returns a ``{relative_path: content}`` map with:
    - ``tests/load/test_load.py`` — Jubilant-based load test exercising
      actions, config changes, and scaling under concurrent load.
    - ``tests/load/conftest.py`` — shared fixtures.
    - ``tests/load/k6_http.js`` — k6 HTTP script (only when the charm
      exposes an HTTP port via config or containers).

    The tests are designed to measure throughput and settling time, not
    correctness — correctness is covered by integration tests.
    """
    actions = metadata.get("actions", {})
    config = metadata.get("config", {}).get("options", {})
    containers = metadata.get("containers", {})

    files: dict[str, str] = {}

    # -- conftest.py --------------------------------------------------------

    files["tests/load/conftest.py"] = (
        '"""Shared fixtures for load tests."""\n'
        "\n"
        "import jubilant\n"
        "import pytest\n"
        "\n"
        "\n"
        '@pytest.fixture(scope="module")\n'
        "def juju():\n"
        '    """Provide a Jubilant Juju instance with a temporary model."""\n'
        "    j = jubilant.Juju()\n"
        f'    j.add_model("{charm_name}-load")\n'
        "    yield j\n"
        f'    j.destroy_model("{charm_name}-load", force=True)\n'
        "\n"
        "\n"
        '@pytest.fixture(scope="module")\n'
        "def deployed_app(juju):\n"
        '    """Deploy the charm and wait for active status."""\n'
        "    import pathlib\n"
        "\n"
        "    charm_path = pathlib.Path(__file__).parent.parent.parent\n"
        "    juju.deploy(charm_path)\n"
        f'    juju.wait(apps=["{charm_name}"], status="active", timeout=300)\n'
        f'    return "{charm_name}"\n'
    )

    # -- test_load.py -------------------------------------------------------

    test_sections: list[str] = [
        '"""Load tests — measure throughput and settling time under load."""\n',
        "",
        "import time\n",
        "\n",
    ]

    # Action throughput tests.
    if actions:
        for action_name in actions:
            fn_name = action_name.replace("-", "_")
            test_sections.append(
                f"def test_action_{fn_name}_throughput(juju, deployed_app):\n"
                f'    """Run {action_name} repeatedly and measure throughput."""\n'
                f"    iterations = 10\n"
                f"    start = time.monotonic()\n"
                f"    failures = 0\n"
                f"    for _ in range(iterations):\n"
                f"        result = juju.run_action(\n"
                f'            f"{{deployed_app}}/leader", "{action_name}"\n'
                f"        )\n"
                f'        if result.status != "completed":\n'
                f"            failures += 1\n"
                f"    elapsed = time.monotonic() - start\n"
                f"    rate = iterations / elapsed if elapsed > 0 else 0\n"
                f'    print(f"\\n{action_name}: {{iterations}} runs in {{elapsed:.1f}}s '
                f'({{rate:.1f}} ops/s, {{failures}} failures)")\n'
                f"    assert failures == 0\n"
                f"\n"
                f"\n"
            )

    # Config change settling time.
    if config:
        # Pick the first config option for the test.
        opt_name = next(iter(config))
        opt_data = config[opt_name]
        opt_type = opt_data.get("type", "string")
        if opt_type == "boolean":
            val_a, val_b = "true", "false"
        elif opt_type == "int":
            val_a, val_b = "1", "2"
        elif opt_type == "float":
            val_a, val_b = "1.0", "2.0"
        else:
            val_a, val_b = "value-a", "value-b"

        test_sections.append(
            "def test_config_change_settling_time(juju, deployed_app):\n"
            '    """Measure how long the charm takes to settle after config changes."""\n'
            "    iterations = 5\n"
            "    times = []\n"
            "    for i in range(iterations):\n"
            f'        val = "{val_a}" if i % 2 == 0 else "{val_b}"\n'
            f'        juju.config(deployed_app, {{"{opt_name}": val}})\n'
            "        start = time.monotonic()\n"
            '        juju.wait(apps=[deployed_app], status="active", timeout=120)\n'
            "        times.append(time.monotonic() - start)\n"
            "    avg = sum(times) / len(times)\n"
            '    print(f"\\nConfig settling: avg {avg:.1f}s over {iterations} changes")\n'
            '    assert avg < 60, f"Config changes take too long to settle: {avg:.1f}s"\n'
            "\n"
            "\n"
        )

    # Scaling test.
    test_sections.append(
        "def test_scale_up_settling_time(juju, deployed_app):\n"
        '    """Measure settling time when scaling from 1 to 3 units."""\n'
        "    juju.scale(deployed_app, 3)\n"
        "    start = time.monotonic()\n"
        '    juju.wait(apps=[deployed_app], status="active", timeout=600)\n'
        "    elapsed = time.monotonic() - start\n"
        '    print(f"\\nScale 1→3: settled in {elapsed:.1f}s")\n'
        "    status = juju.status()\n"
        "    assert len(status.apps[deployed_app].units) == 3\n"
        "    # Scale back down.\n"
        "    juju.scale(deployed_app, 1)\n"
        '    juju.wait(apps=[deployed_app], status="active", timeout=300)\n'
        "\n"
        "\n"
    )

    files["tests/load/test_load.py"] = "".join(test_sections).rstrip() + "\n"

    # -- k6 HTTP script (only for web-facing charms) ------------------------

    http_port = _detect_http_port(config, containers)
    if http_port:
        files["tests/load/k6_http.js"] = _generate_k6_script(charm_name, http_port)

    return files


def _detect_http_port(
    config: dict[str, Any],
    containers: dict[str, Any],
) -> int | None:
    """Heuristically detect an HTTP port from config or containers.

    Returns a port number if one is found, or ``None``.
    """
    # Check config for port-like options.
    for opt_name, opt_data in config.items():
        if "port" in opt_name.lower() and opt_data.get("type") in ("int", "integer"):
            default = opt_data.get("default")
            if isinstance(default, int) and 80 <= default <= 65535:
                return default

    # Check container ports (charmcraft.yaml v2 uses "ports" in containers).
    for _ctr_name, ctr_data in containers.items():
        if not isinstance(ctr_data, dict):
            continue
        for port_entry in ctr_data.get("ports", []):
            if isinstance(port_entry, dict):
                target = port_entry.get("target")
                if isinstance(target, int) and 80 <= target <= 65535:
                    return target
    return None


def _generate_k6_script(charm_name: str, port: int) -> str:
    """Generate a k6 HTTP load test script."""
    return (
        "// k6 HTTP load test for " + charm_name + "\n"
        "//\n"
        "// Usage:\n"
        "//   # Get the unit IP:\n"
        f"//   IP=$(juju status {charm_name} --format=json | "
        "jq -r '.applications.\"" + charm_name + "\".units | to_entries[0].value.address')\n"
        f"//   k6 run --env TARGET=$IP:{port} tests/load/k6_http.js\n"
        "//\n"
        "// Requires: k6 (https://k6.io/docs/get-started/installation/)\n"
        "\n"
        "import http from 'k6/http';\n"
        "import { check, sleep } from 'k6';\n"
        "\n"
        "export const options = {\n"
        "  stages: [\n"
        "    { duration: '30s', target: 10 },  // ramp up\n"
        "    { duration: '1m',  target: 10 },  // sustained\n"
        "    { duration: '30s', target: 0 },   // ramp down\n"
        "  ],\n"
        "  thresholds: {\n"
        "    http_req_duration: ['p(95)<500'],  // 95% of requests under 500ms\n"
        "    http_req_failed: ['rate<0.01'],    // <1% failure rate\n"
        "  },\n"
        "};\n"
        "\n"
        "const BASE = `http://${__ENV.TARGET || 'localhost:" + str(port) + "'}`;\n"
        "\n"
        "export default function () {\n"
        "  const res = http.get(`${BASE}/`);\n"
        "  check(res, {\n"
        "    'status is 200': (r) => r.status === 200,\n"
        "  });\n"
        "  sleep(0.1);\n"
        "}\n"
    )


class GenerateLoadTestTool(Tool):
    """Generate load test scripts for a charm."""

    @property
    def name(self) -> str:
        return "generate_load_test"

    @property
    def description(self) -> str:
        return (
            "Generate load test scripts from charmcraft.yaml. Produces "
            "Jubilant-based tests measuring action throughput, config "
            "change settling time, and scaling behaviour. For web-facing "
            "charms, also generates a k6 HTTP load test script."
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
                "charm_name": {
                    "type": "string",
                    "description": ("Charm name. If omitted, read from charmcraft.yaml."),
                },
            },
        }

    async def execute(self, path: str = ".", charm_name: str | None = None) -> ToolResult:
        """Generate load test files in the charm directory."""
        charm_dir = Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        charmcraft_yaml = charm_dir / "charmcraft.yaml"
        if not charmcraft_yaml.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"charmcraft.yaml not found in {path}",
            )

        try:
            metadata = yaml.safe_load(charmcraft_yaml.read_text())
            if not isinstance(metadata, dict):
                metadata = {}
        except yaml.YAMLError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to parse charmcraft.yaml: {exc}",
            )

        if not charm_name:
            charm_name = metadata.get("name", charm_dir.name)

        files = generate_load_test(charm_name, metadata)

        written: list[str] = []
        for rel_path, content in files.items():
            full_path = charm_dir / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            written.append(rel_path)

        has_k6 = any(f.endswith(".js") for f in written)
        summary = (
            f"Generated load test scripts for '{charm_name}' "
            f"({len(written)} files):\n"
            + "\n".join(f"  {f}" for f in sorted(written))
            + "\n\nRun with: uv run pytest tests/load/ -v -s"
            + ("\nHTTP load test: k6 run tests/load/k6_http.js" if has_k6 else "")
        )

        return ToolResult(
            success=True,
            output=summary,
            data={
                "charm_name": charm_name,
                "file_count": len(written),
                "files": sorted(written),
                "has_k6": has_k6,
            },
        )
