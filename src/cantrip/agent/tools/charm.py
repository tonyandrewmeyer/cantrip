"""Charm scaffolding and management tools."""

import subprocess
from pathlib import Path
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult


class CharmcraftInitTool(Tool):
    """Tool to initialise a new charm with charmcraft."""

    @property
    def name(self) -> str:
        return "charmcraft_init"

    @property
    def description(self) -> str:
        return (
            "Initialise a new charm using charmcraft init. "
            "This creates the basic charm structure with src/charm.py, "
            "charmcraft.yaml, and test scaffolding."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the charm (e.g., 'my-app')",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to create the charm in",
                    "default": ".",
                },
                "profile": {
                    "type": "string",
                    "description": (
                        "Charm profile. Use 'machine' or 'kubernetes' for custom charms, "
                        "or a framework profile for 12-factor apps."
                    ),
                    "enum": [
                        "machine",
                        "kubernetes",
                        "flask-framework",
                        "django-framework",
                        "fastapi-framework",
                        "go-framework",
                        "express-framework",
                        "spring-boot-framework",
                    ],
                    "default": "kubernetes",
                },
            },
            "required": ["name"],
        }

    async def execute(
        self,
        name: str,
        path: str = ".",
        profile: str = "kubernetes",
    ) -> ToolResult:
        """Run charmcraft init."""
        try:
            target_path = Path(path) / name
            target_path.mkdir(parents=True, exist_ok=True)

            result = subprocess.run(
                ["charmcraft", "init", f"--profile={profile}", f"--name={name}"],
                cwd=target_path,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "charmcraft init failed",
                )

            # Ensure .cantrip is in the charm's .gitignore.
            gitignore = target_path / ".gitignore"
            if gitignore.exists():
                content = gitignore.read_text()
                if ".cantrip" not in content:
                    gitignore.write_text(content.rstrip("\n") + "\n.cantrip\n")
            else:
                gitignore.write_text(".cantrip\n")

            return ToolResult(
                success=True,
                output=f"Initialised charm '{name}' at {target_path}\n{result.stdout}",
                data={"path": str(target_path), "profile": profile},
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft not found. Is it installed?",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft init timed out",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class CharmcraftPackTool(Tool):
    """Tool to pack a charm."""

    @property
    def name(self) -> str:
        return "charmcraft_pack"

    @property
    def description(self) -> str:
        return "Pack the charm into a .charm file for deployment."

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
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """Run charmcraft pack."""
        try:
            charm_path = Path(path).resolve()

            result = subprocess.run(
                ["charmcraft", "pack"],
                cwd=charm_path,
                capture_output=True,
                text=True,
                timeout=300,  # Packing can take a while
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "charmcraft pack failed",
                )

            # Find the created .charm file
            charm_files = list(charm_path.glob("*.charm"))
            charm_file = charm_files[0] if charm_files else None

            return ToolResult(
                success=True,
                output=f"Packed charm successfully\n{result.stdout}",
                data={
                    "path": str(charm_path),
                    "charm_file": str(charm_file) if charm_file else None,
                },
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft not found. Is it installed?",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft pack timed out",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class CharmcraftFetchLibsTool(Tool):
    """Tool to fetch charm libraries."""

    @property
    def name(self) -> str:
        return "charmcraft_fetch_libs"

    @property
    def description(self) -> str:
        return "Fetch charm libraries defined in charmcraft.yaml."

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
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """Run charmcraft fetch-libs."""
        try:
            charm_path = Path(path).resolve()

            result = subprocess.run(
                ["charmcraft", "fetch-libs"],
                cwd=charm_path,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "charmcraft fetch-libs failed",
                )

            return ToolResult(
                success=True,
                output=f"Fetched libraries\n{result.stdout}",
                data={"path": str(charm_path)},
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft not found. Is it installed?",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="charmcraft fetch-libs timed out",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class AnalyseFrameworkTool(Tool):
    """Tool to analyse a codebase and detect its framework."""

    @property
    def name(self) -> str:
        return "analyse_framework"

    @property
    def description(self) -> str:
        return (
            "Analyse a codebase to detect its framework (Flask, Django, FastAPI, Go, etc.) "
            "and gather information for charm creation."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the application codebase",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str) -> ToolResult:
        """Analyse the codebase."""
        try:
            app_path = Path(path).resolve()
            if not app_path.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path not found: {path}",
                )

            findings = {
                "framework": None,
                "language": None,
                "files_found": [],
                "suggestions": [],
            }

            # Check for Python frameworks
            requirements = app_path / "requirements.txt"
            pyproject = app_path / "pyproject.toml"
            setup_py = app_path / "setup.py"

            python_deps = ""
            if requirements.exists():
                findings["files_found"].append("requirements.txt")
                python_deps = requirements.read_text().lower()
            if pyproject.exists():
                findings["files_found"].append("pyproject.toml")
                python_deps += pyproject.read_text().lower()
            if setup_py.exists():
                findings["files_found"].append("setup.py")

            if python_deps:
                findings["language"] = "python"
                if "flask" in python_deps:
                    findings["framework"] = "flask"
                    findings["suggestions"].append("Use 12-factor paas-charm base")
                elif "django" in python_deps:
                    findings["framework"] = "django"
                    findings["suggestions"].append("Use 12-factor paas-charm base")
                elif "fastapi" in python_deps:
                    findings["framework"] = "fastapi"
                    findings["suggestions"].append("Use 12-factor paas-charm base")

            # Check for Go
            go_mod = app_path / "go.mod"
            if go_mod.exists():
                findings["files_found"].append("go.mod")
                findings["language"] = "go"
                findings["framework"] = "go"
                findings["suggestions"].append("Use 12-factor paas-charm base")

            # Check for Node.js
            package_json = app_path / "package.json"
            if package_json.exists():
                findings["files_found"].append("package.json")
                findings["language"] = "javascript"
                # Could check for express, next, etc.

            # Check for existing charm structure
            charmcraft_yaml = app_path / "charmcraft.yaml"
            if charmcraft_yaml.exists():
                findings["files_found"].append("charmcraft.yaml")
                findings["suggestions"].append("Existing charm found - will modify")

            # Build output
            output_lines = []
            if findings["language"]:
                output_lines.append(f"Language: {findings['language']}")
            if findings["framework"]:
                output_lines.append(f"Framework: {findings['framework']}")
            if findings["files_found"]:
                output_lines.append(f"Files found: {', '.join(findings['files_found'])}")
            if findings["suggestions"]:
                output_lines.append(f"Suggestions: {'; '.join(findings['suggestions'])}")

            if not output_lines:
                output_lines.append("Could not detect framework. Manual configuration needed.")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                data=findings,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
