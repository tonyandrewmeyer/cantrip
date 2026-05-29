"""Juju lifecycle tools: deploy, refresh, add/destroy model, remove application."""

import asyncio
import functools
import pathlib
import shutil
from typing import Any

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.juju import _common


class JujuDeployTool(Tool):
    """Tool to deploy a charm."""

    @property
    def name(self) -> str:
        return "juju_deploy"

    @property
    def description(self) -> str:
        return "Deploy a charm to the current Juju model."

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        target = arguments.get("app_name") or arguments.get("charm")
        if not target:
            return "Deploying…"
        # Path-shaped charms (./redis.charm) read better with their basename.
        target = pathlib.Path(str(target)).name if "/" in str(target) else target
        return f"Deploying {target}…"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "charm": {
                    "type": "string",
                    "description": "Charm name or path to .charm file",
                },
                "app_name": {
                    "type": "string",
                    "description": "Application name (defaults to charm name)",
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "config": {
                    "type": "object",
                    "description": "Configuration options as key-value pairs",
                },
                "num_units": {
                    "type": "integer",
                    "description": "Number of units to deploy",
                    "default": 1,
                },
                "resources": {
                    "type": "object",
                    "description": (
                        "Named resources as key-value pairs. "
                        "For 12-factor charms: {'oci-image': 'localhost:32000/my-app:latest'}"
                    ),
                },
                "trust": {
                    "type": "boolean",
                    "description": "Grant the charm access to cloud credentials.",
                    "default": False,
                },
                "channel": {
                    "type": "string",
                    "description": "Charmhub channel to deploy from (e.g. 'latest/edge').",
                },
                "base": {
                    "type": "string",
                    "description": "Ubuntu base for the charm (e.g. 'ubuntu@24.04').",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true to deploy when the target controller is "
                        "non-local (or in the operator's production_controllers "
                        "list). Show the operator the controller name and cloud "
                        "and ask them to confirm before setting this."
                    ),
                    "default": False,
                },
            },
            "required": ["charm"],
        }

    async def execute(
        self,
        charm: str,
        app_name: str | None = None,
        model: str | None = None,
        config: dict[str, Any] | None = None,
        num_units: int = 1,
        resources: dict[str, str] | None = None,
        trust: bool = False,
        channel: str | None = None,
        base: str | None = None,
        confirmed: bool = False,
    ) -> ToolResult:
        """Deploy a charm."""
        blocked, reason = _common.controller_confirm_required(
            "juju_deploy", model=model, confirmed=confirmed
        )
        if blocked:
            return ToolResult(success=False, output="", error=reason)
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )
        temp_copy: pathlib.Path | None = None
        try:
            juju = _common.jubilant.Juju(model=model)
            charm, temp_copy = self._resolve_and_stage_charm(charm)
            deploy_args = self._build_deploy_args(
                charm,
                app_name=app_name,
                config=config,
                num_units=num_units,
                resources=resources,
                trust=trust,
                channel=channel,
                base=base,
            )
            await asyncio.wait_for(
                asyncio.to_thread(functools.partial(juju.deploy, **deploy_args)),
                timeout=300,
            )
            return self._deploy_success_result(charm, app_name, model)
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju deploy timed out — the operation is taking too long.",
            )
        except (
            _common.jubilant.CLIError,
            _common.jubilant.TaskError,
            OSError,
            ValueError,
        ) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        finally:
            if temp_copy is not None and temp_copy.exists():
                temp_copy.unlink(missing_ok=True)

    @staticmethod
    def _resolve_and_stage_charm(charm: str) -> tuple[str, pathlib.Path | None]:
        """Resolve a local ``.charm`` path and stage it for snap confinement.

        Returns the (possibly rewritten) charm reference plus a temp copy that
        the caller must clean up, or ``None`` when nothing was staged.

        The Juju snap uses strict confinement and cannot read files outside
        the user's home directory — paths under ``/tmp`` are copied to
        ``~/snap/juju/common/`` before deploy.
        """
        # Resolve local .charm paths to absolute so juju doesn't misinterpret
        # them as Charmhub names.
        charm_path = _common.pathlib.Path(charm)
        if charm_path.suffix == ".charm" and charm_path.exists():
            charm = str(charm_path.resolve())
        elif not charm_path.is_absolute() and (_common.pathlib.Path.cwd() / charm_path).exists():
            charm = str((_common.pathlib.Path.cwd() / charm_path).resolve())
        charm_file = _common.pathlib.Path(charm)
        if charm_file.suffix != ".charm" or not charm_file.exists():
            return charm, None
        home = _common.pathlib.Path.home()
        if str(charm_file).startswith(str(home)):
            return charm, None
        snap_dir = home / "snap" / "juju" / "common"
        snap_dir.mkdir(parents=True, exist_ok=True)
        temp_copy = snap_dir / charm_file.name
        shutil.copy2(charm_file, temp_copy)
        return str(temp_copy), temp_copy

    @staticmethod
    def _build_deploy_args(
        charm: str,
        *,
        app_name: str | None,
        config: dict[str, Any] | None,
        num_units: int,
        resources: dict[str, str] | None,
        trust: bool,
        channel: str | None,
        base: str | None,
    ) -> dict[str, Any]:
        deploy_args: dict[str, Any] = {"charm": charm}
        if app_name:
            deploy_args["app"] = app_name
        if config:
            deploy_args["config"] = config
        if num_units != 1:
            deploy_args["num_units"] = num_units
        if resources:
            deploy_args["resources"] = resources
        if trust:
            deploy_args["trust"] = True
        if channel:
            deploy_args["channel"] = channel
        if base:
            deploy_args["base"] = base
        return deploy_args

    @staticmethod
    def _deploy_success_result(charm: str, app_name: str | None, model: str | None) -> ToolResult:
        display_name = app_name or pathlib.Path(charm).stem
        caption = f"Deployed {display_name}"
        if model:
            caption += f" to {model}"
        return ToolResult(
            success=True,
            output=f"Deployed {charm}" + (f" as {app_name}" if app_name else ""),
            data={"charm": charm, "app_name": app_name or charm},
            caption=caption,
        )


class BundleDeployTool(Tool):
    """Deploy an existing Juju bundle.yaml, optionally with overlays.

    Juju bundles are deprecated — this tool exists so Cantrip can work
    with the many legacy deployments that still ship as bundles.  For
    new multi-charm deployments, use ``juju_deploy`` + ``juju_relate``
    to generate a series of individual commands rather than authoring
    a new bundle.
    """

    @property
    def name(self) -> str:
        return "bundle_deploy"

    @property
    def description(self) -> str:
        return (
            "Deploy an existing Juju bundle.yaml (optionally with one or "
            "more overlay files).  Use this for legacy bundle-based "
            "deployments only; prefer juju_deploy + juju_relate for new "
            "multi-charm deployments."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the bundle.yaml file.",
                },
                "overlays": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of overlay-bundle files applied on "
                        "top of the base bundle, in order.  Each overlay "
                        "may add, remove, or modify applications, "
                        "relations, machines, or the model's config."
                    ),
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified).",
                },
                "trust": {
                    "type": "boolean",
                    "description": (
                        "Grant trust to every application in the bundle "
                        "that requests it (maps to ``--trust``)."
                    ),
                    "default": False,
                },
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        overlays: list[str] | None = None,
        model: str | None = None,
        trust: bool = False,
    ) -> ToolResult:
        """Deploy a bundle."""
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        # Resolve the bundle path first so we can fail early with a
        # clear error rather than passing a missing path to Juju.
        bundle_path = _common.pathlib.Path(path)
        if not bundle_path.is_absolute():
            bundle_path = (_common.pathlib.Path.cwd() / bundle_path).resolve()
        if not bundle_path.is_file():
            return ToolResult(
                success=False,
                output="",
                error=f"Bundle file not found: {bundle_path}",
            )

        overlay_paths: list[pathlib.Path] = []
        for overlay in overlays or []:
            overlay_path = _common.pathlib.Path(overlay)
            if not overlay_path.is_absolute():
                overlay_path = (_common.pathlib.Path.cwd() / overlay_path).resolve()
            if not overlay_path.is_file():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Overlay file not found: {overlay_path}",
                )
            overlay_paths.append(overlay_path)

        try:
            juju = _common.jubilant.Juju(model=model)

            deploy_args: dict[str, Any] = {"charm": str(bundle_path)}
            if overlay_paths:
                deploy_args["overlays"] = [str(p) for p in overlay_paths]
            if trust:
                deploy_args["trust"] = True

            await asyncio.wait_for(
                asyncio.to_thread(functools.partial(juju.deploy, **deploy_args)),
                timeout=600,
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="bundle deploy timed out — the operation is taking too long.",
            )
        except (
            _common.jubilant.CLIError,
            _common.jubilant.TaskError,
            OSError,
            ValueError,
        ) as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )

        overlay_note = f" with {len(overlay_paths)} overlay(s)" if overlay_paths else ""
        return ToolResult(
            success=True,
            output=f"Deployed bundle {bundle_path}{overlay_note}",
            data={
                "bundle_path": str(bundle_path),
                "overlays": [str(p) for p in overlay_paths],
                "trust": trust,
            },
            caption=f"Deployed bundle {bundle_path.name}"
            + (f" (+{len(overlay_paths)} overlay)" if overlay_paths else ""),
        )


class JujuRefreshTool(Tool):
    """Tool to refresh (upgrade) a deployed charm."""

    @property
    def name(self) -> str:
        return "juju_refresh"

    @property
    def description(self) -> str:
        return "Refresh a deployed charm with a new version or local .charm file."

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        app = arguments.get("app_name")
        return f"Refreshing {app}…" if app else "Refreshing…"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Application name to refresh",
                },
                "path": {
                    "type": "string",
                    "description": "Path to local .charm file",
                },
                "model": {
                    "type": "string",
                    "description": "Model name",
                },
                "resources": {
                    "type": "object",
                    "description": (
                        "Named resources as key-value pairs. "
                        "For 12-factor charms: {'oci-image': 'localhost:32000/my-app:latest'}"
                    ),
                },
                "channel": {
                    "type": "string",
                    "description": "Charmhub channel to refresh from (e.g. 'latest/edge').",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true to refresh when the target controller is "
                        "non-local (or in the operator's production_controllers "
                        "list). Show the operator the controller name and cloud "
                        "and ask them to confirm before setting this."
                    ),
                    "default": False,
                },
            },
            "required": ["app_name"],
        }

    async def execute(
        self,
        app_name: str,
        path: str | None = None,
        model: str | None = None,
        resources: dict[str, str] | None = None,
        channel: str | None = None,
        confirmed: bool = False,
    ) -> ToolResult:
        """Refresh a charm."""
        blocked, reason = _common.controller_confirm_required(
            "juju_refresh", model=model, confirmed=confirmed
        )
        if blocked:
            return ToolResult(success=False, output="", error=reason)

        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        temp_copy: pathlib.Path | None = None
        try:
            juju = _common.jubilant.Juju(model=model)
            refresh_args: dict[str, Any] = {"app": app_name}
            if path:
                # Resolve relative .charm paths to absolute first — the
                # snap-confined juju runs from its own cwd and cannot
                # reach a path like ``./mycharm.charm`` even when it
                # exists in the user's working directory.  Mirrors the
                # deploy path's resolution.
                charm_path = _common.pathlib.Path(path)
                if charm_path.suffix == ".charm" and charm_path.exists():
                    path = str(charm_path.resolve())
                elif (
                    not charm_path.is_absolute()
                    and (_common.pathlib.Path.cwd() / charm_path).exists()
                ):
                    path = str((_common.pathlib.Path.cwd() / charm_path).resolve())
                # Copy to snap-accessible path if needed (same as deploy).
                charm_file = _common.pathlib.Path(path)
                if charm_file.suffix == ".charm" and charm_file.exists():
                    home = _common.pathlib.Path.home()
                    if not str(charm_file).startswith(str(home)):
                        snap_dir = home / "snap" / "juju" / "common"
                        snap_dir.mkdir(parents=True, exist_ok=True)
                        temp_copy = snap_dir / charm_file.name
                        shutil.copy2(charm_file, temp_copy)
                        path = str(temp_copy)
                refresh_args["path"] = path
            if resources:
                refresh_args["resources"] = resources
            if channel:
                refresh_args["channel"] = channel

            await _common._run_juju(juju.refresh, **refresh_args)

            return ToolResult(
                success=True,
                output=f"Refreshed {app_name}" + (f" from {path}" if path else ""),
                data={"app_name": app_name, "path": path},
                caption=f"Refreshed {app_name}" + (f" → {channel}" if channel else ""),
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju refresh timed out — the controller may be unavailable.",
            )
        except _common.jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        finally:
            if temp_copy is not None and temp_copy.exists():
                temp_copy.unlink(missing_ok=True)


class JujuAddModelTool(Tool):
    """Tool to create a new Juju model."""

    @property
    def name(self) -> str:
        return "juju_add_model"

    @property
    def description(self) -> str:
        return (
            "Create a new Juju model. Use this for dev models or a dedicated COS model. "
            "For 12-factor / PaaS charms (flask-framework, django-framework, etc.), "
            "specify cloud='k8s' to create the model on a Kubernetes cloud."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Name for the new model",
                },
                "cloud": {
                    "type": "string",
                    "description": (
                        "Cloud (or cloud/region) to create the model on. "
                        "Use 'k8s' for Kubernetes charms, 'localhost' for machine charms. "
                        "Defaults to the controller's default cloud."
                    ),
                },
            },
            "required": ["model"],
        }

    async def execute(self, model: str, cloud: str | None = None) -> ToolResult:
        """Create a Juju model."""
        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju()
            await _common._run_juju(juju.add_model, model, cloud=cloud)

            suffix = f" on cloud '{cloud}'" if cloud else ""
            return ToolResult(
                success=True,
                output=f"Model '{model}' created{suffix}.",
                data={"model": model, "cloud": cloud},
                caption=f"Added model {model}" + (f" on {cloud}" if cloud else ""),
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju add-model timed out — the controller may be unavailable.",
            )
        except _common.jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuDestroyModelTool(Tool):
    """Tool to destroy a Juju model."""

    @property
    def name(self) -> str:
        return "juju_destroy_model"

    @property
    def description(self) -> str:
        return "Destroy a Juju model and all its applications. Use with caution."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Name of the model to destroy",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force destruction, ignoring errors",
                    "default": False,
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true to destroy when the target controller is "
                        "non-local (or in the operator's production_controllers "
                        "list). Show the operator the controller name and cloud "
                        "and ask them to confirm before setting this."
                    ),
                    "default": False,
                },
            },
            "required": ["model"],
        }

    async def execute(
        self, model: str, force: bool = False, confirmed: bool = False
    ) -> ToolResult:
        """Destroy a Juju model."""
        # Phase 10b: production-controller guard fires *before* the
        # blanket destructive gate so operators see "production
        # controller X" in the error rather than a generic policy
        # message.
        blocked, reason = _common.controller_confirm_required(
            "juju_destroy_model", model=model, confirmed=confirmed
        )
        if blocked:
            return ToolResult(success=False, output="", error=reason)

        # Phase 80.5: destructive-command gate.  Refuses unless a
        # policy layer explicitly sets ``approve_destructive: true``.
        from cantrip.agent.policy.policy import destructive_gate

        approved, reason = destructive_gate("juju_destroy_model")
        if not approved:
            return ToolResult(success=False, output="", error=reason)

        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju()
            await _common._run_juju(
                juju.destroy_model,
                model,
                force=force,
                destroy_storage=True,
                no_wait=force,
            )

            return ToolResult(
                success=True,
                output=f"Model '{model}' destruction initiated.",
                data={"model": model, "force": force},
                caption=f"Destroyed {model}" + (" (force)" if force else ""),
            )
        except TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error="juju destroy-model timed out — the controller may be unavailable.",
            )
        except _common.jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )


class JujuRemoveApplicationTool(Tool):
    """Tool to remove a single application from a model."""

    @property
    def name(self) -> str:
        return "juju_remove_application"

    @property
    def description(self) -> str:
        return (
            "Remove a single application from the current Juju model. "
            "This does not destroy the model itself."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Application name to remove",
                },
                "model": {
                    "type": "string",
                    "description": "Model name (uses current model if not specified)",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force removal even if the application has errors.",
                    "default": False,
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true to remove when the target controller is "
                        "non-local (or in the operator's production_controllers "
                        "list). Show the operator the controller name and cloud "
                        "and ask them to confirm before setting this."
                    ),
                    "default": False,
                },
            },
            "required": ["app_name"],
        }

    async def execute(
        self,
        app_name: str,
        model: str | None = None,
        force: bool = False,
        confirmed: bool = False,
    ) -> ToolResult:
        """Remove an application."""
        # Phase 10b: production-controller guard fires *before* the
        # blanket destructive gate so operators see "production
        # controller X" in the error rather than a generic policy
        # message.
        blocked, reason = _common.controller_confirm_required(
            "juju_remove_application", model=model, confirmed=confirmed
        )
        if blocked:
            return ToolResult(success=False, output="", error=reason)

        # Phase 80.5: destructive-command gate.  Refuses unless a
        # policy layer explicitly sets ``approve_destructive: true``.
        from cantrip.agent.policy.policy import destructive_gate

        approved, reason = destructive_gate("juju_remove_application")
        if not approved:
            return ToolResult(success=False, output="", error=reason)

        if not _common._juju_available():
            return ToolResult(
                success=False,
                output="",
                error="Juju CLI not found. Is Juju installed?",
            )

        try:
            juju = _common.jubilant.Juju(model=model)
            await _common._run_juju(juju.remove_application, app_name, force=force)
            return ToolResult(
                success=True,
                output=f"Removed application {app_name}.",
                data={"app_name": app_name},
                caption=f"Removed {app_name}" + (" (force)" if force else ""),
            )
        except (TimeoutError, OSError) as e:
            return ToolResult(success=False, output="", error=str(e))
        except _common.jubilant.CLIError as e:
            return ToolResult(
                success=False,
                output=e.stdout or "",
                error=e.stderr or f"Failed to remove {app_name}",
            )
