"""Rockcraft and OCI registry tools."""

import asyncio
import json
import os
import pathlib
import shutil
import subprocess
from typing import Any

import httpx
import jubilant

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.juju_subprocess import juju_available as _juju_available
from cantrip.agent.tools.rock_contract import (
    SUPPORTED_FRAMEWORKS,
    UnknownFrameworkError,
    check_rock_contract,
)

# The microk8s registry add-on exposes the in-cluster registry at this
# host:port on the dev box.  Canonical's ``k8s`` snap does NOT ship an
# equivalent — operators need to deploy a registry charm or push to a
# remote registry instead.  ``LocalRegistryStatusTool`` probes for one
# at runtime so the agent can pick the right path.
_DEFAULT_LOCAL_REGISTRY = "localhost:32000"

# All rockcraft framework extensions are flagged experimental upstream
# (Flask, Django, FastAPI, Go, ExpressJS, Spring Boot all return
# ``is_experimental() -> True``), so the wrapper unconditionally sets the
# enable flag — same shape as ``RockcraftPackTool``.


class RockcraftInitTool(Tool):
    """Tool to initialise a rockcraft project with a framework profile."""

    @property
    def name(self) -> str:
        return "rockcraft_init"

    @property
    def description(self) -> str:
        return (
            "Initialise a rockcraft project using a framework profile. "
            "This creates a rockcraft.yaml for building an OCI image (rock) "
            "from a 12-factor application."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to initialise in",
                    "default": ".",
                },
                "profile": {
                    "type": "string",
                    "description": "Framework profile for the rock",
                    "enum": [
                        "flask-framework",
                        "django-framework",
                        "fastapi-framework",
                        "go-framework",
                        "express-framework",
                        "spring-boot-framework",
                    ],
                },
            },
            "required": ["profile"],
        }

    async def execute(self, profile: str, path: str = ".") -> ToolResult:
        """Run rockcraft init with the given profile."""
        if not shutil.which("rockcraft"):
            return ToolResult(
                success=False,
                output="",
                error="rockcraft not found. Is it installed?",
            )

        try:
            target_path = pathlib.Path(path).resolve()
            target_path.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            env["ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS"] = "true"

            result = subprocess.run(
                ["rockcraft", "init", f"--profile={profile}"],
                cwd=target_path,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "rockcraft init failed",
                )

            return ToolResult(
                success=True,
                output=f"Initialised rock at {target_path}\n{result.stdout}",
                data={"path": str(target_path), "profile": profile},
                caption=f"Initialised rock ({profile})",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="rockcraft init timed out",
            )


class RockContractCheckTool(Tool):
    """Validate a repo against the rock contract for a 12-factor framework.

    Runs the per-framework checks ported from canonical/skills PR #4 —
    dependency presence, ASGI / WSGI entrypoint location, Maven / Gradle
    consistency for Spring Boot, ``app/package.json`` shape for Express,
    Go module + cmd dir layout — and reports issues (blockers) plus
    advisory warnings.  Use this *before* ``rockcraft pack`` to surface
    misconfiguration up-front instead of after a multi-minute build.
    """

    @property
    def name(self) -> str:
        return "check_rock_contract"

    @property
    def description(self) -> str:
        return (
            "Check whether a repository fits the rockcraft framework "
            "contract for a given 12-factor framework. Returns blocking "
            "issues, advisory warnings, and the list of supported "
            "``base:`` values for the framework. Run this before "
            "``rockcraft init`` / ``rockcraft pack`` to catch dependency, "
            "entrypoint, or build-system problems early. Frameworks: "
            "flask, django, fastapi, express, go, spring-boot."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository path to check.",
                },
                "framework": {
                    "type": "string",
                    "description": "Target 12-factor framework.",
                    "enum": sorted(SUPPORTED_FRAMEWORKS),
                },
            },
            "required": ["path", "framework"],
        }

    async def execute(self, path: str, framework: str) -> ToolResult:
        repo = pathlib.Path(path).resolve()
        if not repo.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Path not found: {path}",
            )

        try:
            report = check_rock_contract(repo, framework)
        except UnknownFrameworkError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        verdict = "FIT" if report.fit else "NO FIT"
        lines = [f"{verdict} for {framework} rock at {repo}"]
        if report.issues:
            lines.append("Issues:")
            lines.extend(f"  - {issue}" for issue in report.issues)
        if report.warnings:
            lines.append("Warnings:")
            lines.extend(f"  - {warning}" for warning in report.warnings)
        lines.append(f"Supported bases: {', '.join(report.supported_bases)}")

        caption = (
            f"check_rock_contract({framework}) → fit"
            if report.fit
            else f"check_rock_contract({framework}) → {len(report.issues)} issues"
        )
        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={
                "framework": report.framework,
                "fit": report.fit,
                "issues": list(report.issues),
                "warnings": list(report.warnings),
                "supported_bases": list(report.supported_bases),
            },
            caption=caption,
        )


class RockcraftPackTool(Tool):
    """Tool to pack a rock (OCI image)."""

    @property
    def name(self) -> str:
        return "rockcraft_pack"

    @property
    def description(self) -> str:
        return (
            "Pack the application into a .rock OCI image file. "
            "The first build may take several minutes as it downloads the Ubuntu base."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory containing rockcraft.yaml",
                    "default": ".",
                },
            },
        }

    async def execute(self, path: str = ".") -> ToolResult:
        """Run rockcraft pack."""
        if not shutil.which("rockcraft"):
            return ToolResult(
                success=False,
                output="",
                error="rockcraft not found. Is it installed?",
            )

        try:
            rock_path = pathlib.Path(path).resolve()

            # Always set the experimental flag — harmless when not needed.
            env = os.environ.copy()
            env["ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS"] = "true"

            result = subprocess.run(
                ["rockcraft", "pack"],
                cwd=rock_path,
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "rockcraft pack failed",
                )

            # Find the resulting .rock file.
            rock_files = list(rock_path.glob("*.rock"))
            rock_file = rock_files[0] if rock_files else None

            if rock_file is not None:
                size_mb = rock_file.stat().st_size / (1024 * 1024)
                caption = f"Packed → {rock_file.name} ({size_mb:.1f} MB)"
            else:
                caption = "Packed rock (no .rock located)"
            return ToolResult(
                success=True,
                output=f"Packed rock successfully\n{result.stdout}",
                data={
                    "path": str(rock_path),
                    "rock_file": str(rock_file) if rock_file else None,
                },
                caption=caption,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="rockcraft pack timed out (600s limit)",
            )


class SkopeoRegistryPushTool(Tool):
    """Tool to push a rock to an OCI registry via skopeo."""

    @property
    def name(self) -> str:
        return "skopeo_registry_push"

    @property
    def description(self) -> str:
        return (
            "Push a .rock file to an OCI container registry using skopeo. "
            "Defaults to localhost:32000 (the MicroK8s built-in registry); "
            "the Canonical 'k8s' snap has no built-in registry — call "
            "local_registry_status first to verify, or pass a remote "
            "registry as 'registry'."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "rock_file": {
                    "type": "string",
                    "description": "Path to the .rock file",
                },
                "image_name": {
                    "type": "string",
                    "description": "Name for the image in the registry",
                },
                "registry": {
                    "type": "string",
                    "description": "Registry address",
                    "default": "localhost:32000",
                },
                "tag": {
                    "type": "string",
                    "description": "Image tag",
                    "default": "latest",
                },
            },
            "required": ["rock_file", "image_name"],
        }

    async def execute(
        self,
        rock_file: str,
        image_name: str,
        registry: str = "localhost:32000",
        tag: str = "latest",
    ) -> ToolResult:
        """Push a rock to a container registry."""
        if not shutil.which("skopeo"):
            return ToolResult(
                success=False,
                output="",
                error="skopeo not found. Is it installed?",
            )

        rock_path = pathlib.Path(rock_file)
        if not rock_path.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Rock file not found: {rock_file}",
            )

        try:
            image_url = f"{registry}/{image_name}:{tag}"
            result = subprocess.run(
                [
                    "skopeo",
                    "copy",
                    "--insecure-policy",
                    "--dest-tls-verify=false",
                    f"oci-archive:{rock_path}",
                    f"docker://{image_url}",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=result.stdout,
                    error=result.stderr or "skopeo push failed",
                )

            return ToolResult(
                success=True,
                output=f"Pushed rock to {image_url}\n{result.stdout}",
                data={"image_url": image_url},
                caption=f"Pushed → {image_url}",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error="skopeo push timed out",
            )


def _strip_registry_scheme(image_ref: str) -> str:
    """Strip any ``docker://`` / ``oci://`` prefix from an image ref.

    Registry refs come in two interchangeable shapes — ``localhost:32000/foo:tag``
    and ``docker://localhost:32000/foo:tag`` — and tools mix them
    freely.  Skopeo wants the ``docker://`` form on the wire, but
    callers tend to pass the bare host:port form.  Normalise so the
    rest of the tool doesn't care.
    """
    for prefix in ("docker://", "oci://"):
        if image_ref.startswith(prefix):
            return image_ref[len(prefix) :]
    return image_ref


class RegistryImageExistsTool(Tool):
    """Verify an OCI image is pullable before referencing it in a deploy.

    Wraps ``skopeo inspect docker://<ref>`` so the agent can short-circuit
    ``ImagePullBackOff`` cycles by checking the image exists *before*
    Juju tries to pull it.  Works against any registry the dev machine
    can reach — public (Docker Hub, ghcr.io, quay.io) or private
    (a deployed ``registry-k8s`` / ``oci-registry`` charm, or the
    microk8s built-in at ``localhost:32000``).  Daemon-free; no Docker
    engine is touched.
    """

    @property
    def name(self) -> str:
        return "registry_image_exists"

    @property
    def description(self) -> str:
        return (
            "Verify an OCI image is pullable from a registry using skopeo inspect. "
            "Use this before juju_deploy to short-circuit ImagePullBackOff loops "
            "when the image reference is wrong or the tag was never pushed. "
            "Accepts public (docker.io/library/foo:tag, ghcr.io/...) or local "
            "(localhost:32000/foo:tag) references."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "image_ref": {
                    "type": "string",
                    "description": (
                        "Full image reference, e.g. 'docker.io/library/redis:7-alpine' "
                        "or 'localhost:32000/my-app:latest'.  An optional 'docker://' "
                        "prefix is stripped automatically."
                    ),
                },
                "insecure": {
                    "type": "boolean",
                    "description": (
                        "Skip TLS verification — needed for the microk8s built-in "
                        "registry at localhost:32000, which serves plain HTTP."
                    ),
                    "default": False,
                },
            },
            "required": ["image_ref"],
        }

    async def execute(self, image_ref: str, insecure: bool = False) -> ToolResult:
        """Run ``skopeo inspect`` against the image reference."""
        if not shutil.which("skopeo"):
            return ToolResult(
                success=False,
                output="",
                error="skopeo not found. Is it installed?",
                caption="skopeo not installed",
            )

        ref = _strip_registry_scheme(image_ref)
        # Default to insecure for localhost — the microk8s built-in
        # registry serves plain HTTP and TLS verification will fail
        # there even though the image is fine.
        if not insecure and ref.startswith("localhost:"):
            insecure = True

        argv = ["skopeo", "inspect"]
        if insecure:
            argv.append("--tls-verify=false")
        argv.append(f"docker://{ref}")

        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"skopeo inspect timed out probing {ref}",
                caption=f"skopeo inspect timed out: {ref}",
            )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            # Common failures the LLM should learn the shape of:
            # "manifest unknown" → tag not pushed, "name unknown" →
            # repo doesn't exist on this registry, "no such host" →
            # registry unreachable.  Surface them verbatim so the
            # agent can decide between fixing the ref vs deploying a
            # registry vs picking a different image.
            return ToolResult(
                success=False,
                output="",
                error=f"Image '{ref}' not pullable: {stderr or 'unknown error'}",
                data={"image_ref": ref, "exists": False},
                caption=f"Image not found: {ref}",
            )

        # ``skopeo inspect`` returns JSON metadata.  Parse it so the
        # agent can show digest / arch / created date without re-running.
        try:
            metadata = json.loads(result.stdout)
        except json.JSONDecodeError:
            metadata = {}

        digest = metadata.get("Digest", "")
        architecture = metadata.get("Architecture", "")
        created = metadata.get("Created", "")
        layers = len(metadata.get("Layers") or [])

        summary_lines = [f"Image '{ref}' exists."]
        if digest:
            summary_lines.append(f"Digest: {digest}")
        if architecture:
            summary_lines.append(f"Architecture: {architecture}")
        if created:
            summary_lines.append(f"Created: {created}")
        if layers:
            summary_lines.append(f"Layers: {layers}")

        return ToolResult(
            success=True,
            output="\n".join(summary_lines),
            data={
                "image_ref": ref,
                "exists": True,
                "digest": digest,
                "architecture": architecture,
                "created": created,
                "layers": layers,
            },
            caption=f"Image exists: {ref}",
        )


class RegistryMirrorTool(Tool):
    """Copy an OCI image from one registry to another via skopeo.

    Use case: dev iteration on a paas-charm or custom K8s charm that
    pulls from a public registry hits Docker Hub rate limits or simply
    wants to avoid round-tripping the public internet on every deploy.
    Mirroring once into the local registry lets every subsequent
    deploy pull from ``localhost:32000`` (microk8s) or whatever
    registry the dev cluster can see.

    Daemon-free — skopeo speaks the registry HTTP protocol directly,
    no Docker engine needed.
    """

    @property
    def name(self) -> str:
        return "registry_mirror"

    @property
    def description(self) -> str:
        return (
            "Copy an OCI image from one registry to another using skopeo. "
            "Common case: mirror a public image into the local registry so "
            "the dev cluster pulls from localhost:32000 instead of hitting "
            "Docker Hub rate limits on every iteration. "
            "Defaults destination to localhost:32000/<basename>:<source-tag> "
            "when only 'source' is given — verify with local_registry_status "
            "first if the substrate is the Canonical 'k8s' snap."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": (
                        "Source image reference, e.g. 'docker.io/library/redis:7-alpine'. "
                        "An optional 'docker://' prefix is stripped automatically."
                    ),
                },
                "target": {
                    "type": "string",
                    "description": (
                        "Destination image reference.  When omitted, defaults to "
                        "'localhost:32000/<basename>:<source-tag>' — only valid on "
                        "microk8s with the registry add-on enabled."
                    ),
                },
                "source_insecure": {
                    "type": "boolean",
                    "description": "Skip TLS verification on the source registry.",
                    "default": False,
                },
                "target_insecure": {
                    "type": "boolean",
                    "description": (
                        "Skip TLS verification on the target registry.  Auto-enabled "
                        "for localhost: targets."
                    ),
                    "default": False,
                },
            },
            "required": ["source"],
        }

    async def execute(
        self,
        source: str,
        target: str | None = None,
        source_insecure: bool = False,
        target_insecure: bool = False,
    ) -> ToolResult:
        """Run ``skopeo copy`` from *source* to *target*."""
        if not shutil.which("skopeo"):
            return ToolResult(
                success=False,
                output="",
                error="skopeo not found. Is it installed?",
                caption="skopeo not installed",
            )

        source_ref = _strip_registry_scheme(source)

        if target is None:
            # Derive ``localhost:32000/<basename>:<tag>`` from the source.
            # Splitting on the last ``/`` peels off any registry / namespace
            # prefix, giving the bare image name + tag.
            basename = source_ref.rsplit("/", 1)[-1]
            if ":" not in basename:
                # Default tag matches Docker convention.
                basename = f"{basename}:latest"
            target_ref = f"{_DEFAULT_LOCAL_REGISTRY}/{basename}"
        else:
            target_ref = _strip_registry_scheme(target)

        # Auto-insecure for localhost — same reasoning as
        # RegistryImageExistsTool: the microk8s registry is plain HTTP.
        if not source_insecure and source_ref.startswith("localhost:"):
            source_insecure = True
        if not target_insecure and target_ref.startswith("localhost:"):
            target_insecure = True

        argv = ["skopeo", "copy", "--insecure-policy"]
        if source_insecure:
            argv.append("--src-tls-verify=false")
        if target_insecure:
            argv.append("--dest-tls-verify=false")
        argv.extend([f"docker://{source_ref}", f"docker://{target_ref}"])

        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"skopeo copy timed out copying {source_ref} → {target_ref}",
                caption=f"skopeo copy timed out: {source_ref}",
            )

        if result.returncode != 0:
            return ToolResult(
                success=False,
                output=result.stdout,
                error=(result.stderr.strip() or "skopeo copy failed"),
                data={"source": source_ref, "target": target_ref},
                caption=f"skopeo copy failed: {source_ref}",
            )

        return ToolResult(
            success=True,
            output=f"Mirrored {source_ref} → {target_ref}\n{result.stdout}",
            data={"source": source_ref, "target": target_ref, "image_url": target_ref},
            caption=f"Mirrored {source_ref} → {target_ref}",
        )


class LocalRegistryStatusTool(Tool):
    """Probe whether a local OCI registry is usable on this dev box.

    Cantrip's tooling defaults to ``localhost:32000`` because that is
    where the microk8s ``registry`` add-on lives — but Canonical's
    ``k8s`` snap has no equivalent, and a fresh ``k8s`` cluster has no
    in-cluster registry at all.  This tool surfaces the truth so the
    agent can pick between (a) pushing to the local registry, (b)
    using a public registry like ghcr.io, or (c) suggesting the user
    deploy a ``registry-k8s`` / ``oci-registry`` charm.
    """

    @property
    def name(self) -> str:
        return "local_registry_status"

    @property
    def description(self) -> str:
        return (
            "Check whether a local OCI registry is reachable on this dev box "
            "(typically the microk8s built-in at localhost:32000). Returns "
            "the URL and a substrate hint, or a message explaining why no "
            "local registry exists (Canonical k8s snap has no built-in one)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": (
                        "Registry URL to probe (default localhost:32000). "
                        "Pass a different URL to check a registry charm "
                        "exposed on a different port."
                    ),
                    "default": _DEFAULT_LOCAL_REGISTRY,
                },
            },
        }

    async def execute(self, url: str = _DEFAULT_LOCAL_REGISTRY) -> ToolResult:
        """Probe ``http://{url}/v2/`` — the registry-v2 spec's discovery endpoint."""
        host_port = _strip_registry_scheme(url)
        # Try HTTP first — the microk8s built-in is plain HTTP.  Fall
        # back to HTTPS so the tool still works against a TLS-enabled
        # local registry (e.g. a deployed registry-k8s with a self-signed cert).
        substrate_hint = self._guess_substrate()
        for scheme in ("http", "https"):
            probe_url = f"{scheme}://{host_port}/v2/"
            try:
                with httpx.Client(timeout=5.0, verify=False) as client:
                    response = client.get(probe_url)
            except httpx.TimeoutException:
                continue
            except httpx.HTTPError:
                continue
            # The registry-v2 API returns 200 (open) or 401 (auth
            # required) on ``/v2/`` — both mean a registry is alive.
            # Any other status / connection failure means "not a registry".
            if response.status_code in (200, 401):
                return ToolResult(
                    success=True,
                    output=(
                        f"Local registry reachable at {probe_url}.\n"
                        f"Substrate hint: {substrate_hint}.\n"
                        f"Use '{host_port}/<image>:<tag>' as the registry "
                        "destination for skopeo_registry_push / registry_mirror."
                    ),
                    data={
                        "available": True,
                        "url": host_port,
                        "scheme": scheme,
                        "substrate_hint": substrate_hint,
                    },
                    caption=f"Registry reachable at {host_port}",
                )

        # Tailor the "not available" message to the substrate so the
        # agent picks the right next step.
        if substrate_hint == "microk8s":
            advice = (
                "MicroK8s is the substrate but the registry add-on is off. "
                "Run 'sudo microk8s enable registry' to bring it up at "
                f"{_DEFAULT_LOCAL_REGISTRY}."
            )
        elif substrate_hint == "k8s":
            advice = (
                "The Canonical 'k8s' snap does not ship a built-in registry. "
                "Either (a) push to a public registry (ghcr.io, docker.io), "
                "(b) deploy a registry charm into the model "
                "(juju deploy registry-k8s) and pass its address explicitly, "
                "or (c) load the rock directly into containerd via "
                "'sudo k8s ctr images import <rock>' (bypasses the registry "
                "entirely; the image then has to be referenced by the name "
                "the rock declares)."
            )
        else:
            advice = (
                "No local registry detected.  Either deploy one as a charm, "
                "enable the microk8s registry add-on, or push to a remote "
                "registry such as ghcr.io."
            )
        return ToolResult(
            success=False,
            output="",
            error=(f"No local registry reachable at {host_port}.\n{advice}"),
            data={
                "available": False,
                "url": host_port,
                "substrate_hint": substrate_hint,
            },
            caption=f"No registry at {host_port} ({substrate_hint})",
        )

    @staticmethod
    def _guess_substrate() -> str:
        """Return ``"k8s"`` / ``"microk8s"`` / ``"unknown"`` based on snaps on PATH.

        The microk8s and ``k8s`` snaps install distinct CLI binaries.
        On a box where both are installed (rare), the canonical ``k8s``
        snap wins — it is the recommended substrate for new charm work,
        and the user's standing preference per project policy.
        """
        if shutil.which("k8s"):
            return "k8s"
        if shutil.which("microk8s"):
            return "microk8s"
        return "unknown"


def _guess_substrate() -> str:
    """Module-level substrate detector — wraps the static method above
    so other tools can call it without an instance.
    """
    return LocalRegistryStatusTool._guess_substrate()


# Containerd ``hosts.d`` template used by the ``k8s`` snap to tell its
# bundled containerd which insecure registries to trust.  Spelled out
# as a plain template (not a dynamic config object) because the file
# format is simple and we surface the rendered text to the operator
# rather than writing it ourselves — no sudo file write inside the
# tool.  See https://github.com/containerd/containerd/blob/main/docs/hosts.md.
_HOSTS_TOML_TEMPLATE = """\
server = "http://{host}"

[host."http://{host}"]
  capabilities = ["pull", "resolve"]
  skip_verify = true
"""


class SetupLocalRegistryTool(Tool):
    """Set up a local OCI registry on the dev cluster.

    Substrate-aware:

    - **microk8s**: enables the built-in ``registry`` add-on, which
      brings up an in-cluster registry at ``localhost:32000``.  One
      ``sudo microk8s enable registry`` and you're done.
    - **canonical k8s snap**: deploys a registry charm into the dev
      Juju model and waits for ``active``.  After the deploy, the
      cluster's containerd needs to be told to trust the registry as
      an insecure HTTP endpoint — the tool does *not* write to
      ``/var/snap/k8s/...`` itself; instead it surfaces the exact
      ``sudo`` block for the operator to apply once.  This keeps the
      tool's blast radius limited to "deployed a charm" and lets the
      operator audit the trust change.

    Use this when ``local_registry_status`` reports no registry is
    reachable and the user wants to push private rocks to a local
    destination instead of a public registry.
    """

    @property
    def name(self) -> str:
        return "setup_local_registry"

    @property
    def description(self) -> str:
        return (
            "Set up a local OCI registry. On microk8s, enables the built-in "
            "add-on at localhost:32000. On the canonical k8s snap, deploys a "
            "registry charm into the dev Juju model and surfaces the "
            "containerd-trust sudo block the operator must apply. Use when "
            "local_registry_status reports no registry is reachable."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "charm_name": {
                    "type": "string",
                    "description": (
                        "Charm name to deploy as the registry on the canonical "
                        "k8s snap (must be a Kubernetes charm).  Default "
                        "'docker-registry-k8s'.  Other candidates seen in the "
                        "wild: 'oci-registry-k8s', 'registry-k8s'.  If the "
                        "default does not exist on Charmhub, run charmhub_search "
                        "with query='registry' first to pick one."
                    ),
                    "default": "docker-registry-k8s",
                },
                "app_name": {
                    "type": "string",
                    "description": "Application name for the deployed registry.",
                    "default": "local-registry",
                },
                "model": {
                    "type": "string",
                    "description": "Juju model to deploy into (default: current model).",
                },
                "channel": {
                    "type": "string",
                    "description": "Charmhub channel for the registry charm.",
                    "default": "latest/stable",
                },
                "wait_timeout": {
                    "type": "integer",
                    "description": "Seconds to wait for the registry to reach active.",
                    "default": 600,
                },
            },
        }

    async def execute(
        self,
        charm_name: str = "docker-registry-k8s",
        app_name: str = "local-registry",
        model: str | None = None,
        channel: str = "latest/stable",
        wait_timeout: int = 600,
    ) -> ToolResult:
        """Dispatch to the substrate-specific setup path."""
        substrate = _guess_substrate()

        if substrate == "microk8s":
            return await self._enable_microk8s_registry()
        if substrate == "k8s":
            return await self._deploy_k8s_registry(
                charm_name=charm_name,
                app_name=app_name,
                model=model,
                channel=channel,
                wait_timeout=wait_timeout,
            )
        return ToolResult(
            success=False,
            output="",
            error=(
                "Cannot detect a supported substrate (neither 'microk8s' nor "
                "'k8s' on PATH).  Run concierge_prepare with preset='k8s' "
                "first, then retry."
            ),
            data={"substrate_hint": "unknown"},
            caption="No substrate detected",
        )

    async def _enable_microk8s_registry(self) -> ToolResult:
        """Run ``sudo microk8s enable registry``."""
        proc = await asyncio.create_subprocess_exec(
            "sudo",
            "microk8s",
            "enable",
            "registry",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(
                success=False,
                output="",
                error="microk8s enable registry timed out after 180 seconds.",
                caption="microk8s enable registry timed out",
            )

        if proc.returncode != 0:
            return ToolResult(
                success=False,
                output=stdout.decode(),
                error=(
                    "microk8s enable registry failed: "
                    + (stderr.decode().strip() or "(no stderr)")
                ),
                caption="microk8s enable registry failed",
            )

        return ToolResult(
            success=True,
            output=(
                "microk8s registry add-on enabled at localhost:32000.\n"
                "Push rocks with skopeo_registry_push and reference them "
                "as 'localhost:32000/<name>:<tag>' in juju_deploy."
            ),
            data={
                "url": "localhost:32000",
                "substrate": "microk8s",
                "needs_containerd_trust": False,
            },
            caption="Enabled microk8s registry at localhost:32000",
        )

    async def _deploy_k8s_registry(
        self,
        *,
        charm_name: str,
        app_name: str,
        model: str | None,
        channel: str,
        wait_timeout: int,
    ) -> ToolResult:
        """Deploy a registry charm into the dev model on canonical k8s."""
        if not _juju_available():
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Juju CLI not found.  Bootstrap a controller first via "
                    "concierge_prepare with preset='k8s'."
                ),
                caption="Juju CLI not found",
            )

        try:
            juju = jubilant.Juju(model=model)

            # If the registry is already deployed in this model, reuse
            # it.  Saves a 5-minute deploy on every retry of the
            # surrounding "set up local registry" workflow.
            try:
                status = juju.status()
            except jubilant.CLIError as exc:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Cannot reach Juju controller: {exc}",
                    caption="Juju controller unreachable",
                )

            existing = status.apps.get(app_name)
            if existing is not None:
                url = self._registry_url(existing)
                return ToolResult(
                    success=True,
                    output=(
                        f"Registry already deployed as '{app_name}' "
                        f"(charm={existing.charm}).  In-cluster address: {url}.\n"
                        + self._containerd_trust_block(url)
                    ),
                    data={
                        "url": url,
                        "substrate": "k8s",
                        "already_deployed": True,
                        "needs_containerd_trust": True,
                        "app_name": app_name,
                    },
                    caption=f"Reused {app_name} at {url}",
                )

            # Deploy the charm.  Failures here are usually "charm not
            # found on Charmhub" or "wrong substrate" — surface verbatim
            # so the agent can retry with a different ``charm_name``.
            try:
                juju.deploy(charm_name, app_name, channel=channel)
            except jubilant.CLIError as exc:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Failed to deploy '{charm_name}' as '{app_name}': {exc}.\n"
                        "If the charm name is unknown to Charmhub, run "
                        "charmhub_search with query='registry' to find a valid one."
                    ),
                    data={"charm_name": charm_name},
                    caption=f"juju deploy {charm_name} failed",
                )

            try:
                juju.wait(jubilant.all_active, timeout=wait_timeout)
            except jubilant.WaitError as exc:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Registry charm did not reach active within {wait_timeout}s: {exc}.\n"
                        "Check juju_status / juju_debug_log for the unit; the "
                        "charm may be blocked on a config requirement."
                    ),
                    caption=f"{app_name} did not reach active",
                )

            status = juju.status()
            app = status.apps.get(app_name)
            if app is None:
                # Should not happen — wait succeeded — but fail loudly if it does.
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Deploy succeeded but '{app_name}' is missing from "
                        "juju status.  Inspect manually with juju_status."
                    ),
                    caption=f"{app_name} missing post-deploy",
                )

            url = self._registry_url(app)
            return ToolResult(
                success=True,
                output=(
                    f"Deployed '{charm_name}' as '{app_name}' on canonical k8s.\n"
                    f"In-cluster registry address: {url}\n\n" + self._containerd_trust_block(url)
                ),
                data={
                    "url": url,
                    "substrate": "k8s",
                    "already_deployed": False,
                    "needs_containerd_trust": True,
                    "app_name": app_name,
                    "charm_name": charm_name,
                },
                caption=f"Deployed {charm_name} at {url}",
            )
        except (jubilant.CLIError, jubilant.TaskError, OSError) as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Registry setup failed: {exc}",
                caption="setup_local_registry failed",
            )

    @staticmethod
    def _registry_url(app: jubilant.statustypes.AppStatus) -> str:
        """Best-effort ``host:port`` for the deployed registry charm.

        Tries (in order): the app's ``address`` (cluster IP for k8s
        charms), the leader unit's ``public_address``, the leader
        unit's ``address``.  Default port 5000 — the canonical OCI
        registry port; charms that use a different port can be
        recognised from ``open_ports`` and the URL adjusted by the
        caller.
        """
        port = "5000"
        candidates: list[str] = []
        if app.address:
            candidates.append(app.address)
        for unit in app.units.values():
            if unit.public_address:
                candidates.append(unit.public_address)
            if unit.address:
                candidates.append(unit.address)
            for entry in unit.open_ports or ():
                # ``open_ports`` is a list of ``"5000/tcp"`` strings —
                # use the first one we see as the port hint.
                head = entry.split("/", 1)[0]
                if head.isdigit():
                    port = head
                    break
        host = candidates[0] if candidates else "<registry-address-pending>"
        return f"{host}:{port}"

    @staticmethod
    def _containerd_trust_block(url: str) -> str:
        """Render the sudo block the operator runs to trust the registry."""
        rendered = _HOSTS_TOML_TEMPLATE.format(host=url)
        return (
            "Next step — tell the cluster's containerd to trust this insecure registry:\n\n"
            f"  sudo mkdir -p /var/snap/k8s/common/etc/containerd/hosts.d/{url}\n"
            f"  sudo tee /var/snap/k8s/common/etc/containerd/hosts.d/{url}/hosts.toml >/dev/null <<'EOF'\n"
            f"{rendered}EOF\n"
            "  sudo snap restart k8s.containerd\n\n"
            "After containerd restarts, push rocks via skopeo_registry_push "
            f"(registry={url!r}) and reference them in juju_deploy as "
            f"'{url}/<image>:<tag>'."
        )
