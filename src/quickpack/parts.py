"""Parts processing for quick pack.

Supports ``uv``, ``dump``, and ``nil`` plugins.
"""

import fnmatch
import logging
import os
import pathlib
import re
import shutil
import subprocess
from email.parser import Parser as _EmailParser
from typing import Any

import pypi_attest
from quickpack import jujuignore
from quickpack import metadata as _metadata

logger = logging.getLogger(__name__)


class AttestationError(RuntimeError):
    """Raised when attestation verification rejects a dependency."""


def _copy_tree(src: pathlib.Path, dest: pathlib.Path) -> None:
    """Copy a directory tree, creating parents as needed."""
    if not src.is_dir():
        return
    shutil.copytree(str(src), str(dest), dirs_exist_ok=True)


def _match_fileset(path: str, patterns: list[str]) -> bool:
    """Check whether *path* is included by a craft-parts fileset.

    A fileset is a list of glob patterns.  Patterns prefixed with ``-`` are
    exclusions.  If only exclusions are given, all files are included except
    those matching exclusions.  If any inclusion patterns exist, a file must
    match at least one to be included (and must not match any exclusion).
    """
    inclusions = [p for p in patterns if not p.startswith("-")]
    exclusions = [p[1:] for p in patterns if p.startswith("-")]

    for exc in exclusions:
        if fnmatch.fnmatch(path, exc):
            return False

    if not inclusions:
        return True

    return any(fnmatch.fnmatch(path, inc) for inc in inclusions)


def _iter_installed_distributions(
    venv_dir: pathlib.Path,
) -> list[tuple[str, str]]:
    """Return ``(name, version)`` for every distribution installed in *venv_dir*.

    Reads ``*.dist-info/METADATA`` files directly so we do not depend on
    running Python inside the charm's venv.  Unparseable files are
    skipped — attestation checking is best-effort, and the caller
    decides severity.
    """
    site_packages_roots = list(venv_dir.glob("lib/python*/site-packages"))
    dists: list[tuple[str, str]] = []
    parser = _EmailParser()
    for root in site_packages_roots:
        for dist_info in sorted(root.glob("*.dist-info")):
            metadata_path = dist_info / "METADATA"
            if not metadata_path.is_file():
                continue
            try:
                text = metadata_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            headers = parser.parsestr(text)
            name = headers.get("Name")
            version = headers.get("Version")
            if name and version:
                dists.append((name, version))
    return dists


def _verify_installed_attestations(
    venv_dir: pathlib.Path,
    *,
    strict: bool,
) -> None:
    """Check PyPI attestations for every installed distribution.

    Must-have packages are always enforced.  When ``strict`` is True
    (``--verify-attestations``), every package missing a PEP 740
    attestation is a build failure; otherwise non-must-have packages
    are only warned about.  ``UNKNOWN`` results (network/PyPI errors)
    are logged but never fail the build so we degrade gracefully when
    the builder is offline.
    """
    missing_required: list[str] = []
    missing_optional: list[str] = []
    for name, version in _iter_installed_distributions(venv_dir):
        result = pypi_attest.check_provenance(name, version)
        if result.status is pypi_attest.ProvenanceStatus.UNATTESTED:
            entry = f"{name}=={version}"
            if pypi_attest.is_must_have(name):
                missing_required.append(entry)
            else:
                missing_optional.append(entry)
        elif result.status is pypi_attest.ProvenanceStatus.UNKNOWN:
            logger.warning(
                "Could not check PyPI attestations for %s==%s: %s",
                name,
                version,
                result.detail,
            )

    if missing_required:
        raise AttestationError(
            "PyPI attestations missing for required packages: "
            + ", ".join(sorted(missing_required))
            + ". These packages are expected to be published via a trusted "
            "publisher — refusing to pack an unsigned build."
        )

    if missing_optional:
        if strict:
            raise AttestationError(
                "PyPI attestations missing for: "
                + ", ".join(sorted(missing_optional))
                + " (strict mode via --verify-attestations)."
            )
        for entry in missing_optional:
            logger.warning(
                "No PyPI attestation for %s; run with --verify-attestations to enforce.",
                entry,
            )


def _run_uv(
    cmd: list[str],
    *,
    cwd: pathlib.Path,
    env: dict[str, str] | None = None,
) -> None:
    """Run a ``uv`` invocation and re-raise failures with stderr context.

    ``subprocess.run(check=True, capture_output=True)`` raises
    ``CalledProcessError`` on a non-zero exit, but the CLI only catches
    ``FileNotFoundError | ValueError | RuntimeError | OSError`` — letting
    a uv failure (missing lock file, wheel build error, network
    failure) bubble up as an unhandled traceback rather than a clean
    error.  Translate it here so ``quickpack`` users see *why* uv
    failed instead of a Python stack frame.
    """
    try:
        subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or f"exit code {exc.returncode}"
        raise RuntimeError(f"`{' '.join(cmd)}` failed: {detail}") from exc


def process_uv_part(
    charm_dir: pathlib.Path,
    prime_dir: pathlib.Path,
    part_config: dict[str, Any],
    *,
    verify_attestations: bool = False,
    target_python: str | None = None,
) -> None:
    """Process a UV plugin part: copy src/lib and install deps.

    The UV plugin only copies ``src/`` and ``lib/`` from the project
    (not the full tree), then installs Python dependencies into ``venv/``.

    *target_python* is the CPython label (e.g. ``"3.12"``) the unit
    will run — passed straight through to ``uv venv --python`` so the
    resulting ``venv/lib/pythonX.Y/`` directory matches what the unit's
    ``python3`` reads at dispatch.  When ``None`` we fall back to
    whatever the host's ``python3`` resolves to (the historical
    behaviour); that's correct on a host whose system Python matches
    the unit, and broken on a host where ``uv python install`` has
    pulled a newer interpreter into ``$PATH`` (Python 3.14 venv +
    Python 3.12 unit ⇒ ``ModuleNotFoundError: No module named 'ops'``
    at install-hook time).

    When attestation checking runs (always for must-have packages, and
    for every package when ``verify_attestations`` is True) PyPI is
    queried over the network; failures fall back to warnings except for
    must-haves, which are hard failures.
    """
    source = part_config.get("source", ".")
    source_dir = (charm_dir / source).resolve()

    # Copy only src/ and lib/ (matching charmcraft's UV plugin behaviour).
    src_dir = source_dir / "src"
    lib_dir = source_dir / "lib"
    if src_dir.is_dir():
        _copy_tree(src_dir, prime_dir / "src")
    if lib_dir.is_dir():
        _copy_tree(lib_dir, prime_dir / "lib")

    # Install Python dependencies via uv.
    venv_dir = prime_dir / "venv"

    python_spec = target_python or "python3"
    _run_uv(
        [
            "uv",
            "venv",
            "--relocatable",
            "--python",
            python_spec,
            str(venv_dir),
        ],
        cwd=charm_dir,
    )

    sync_cmd = [
        "uv",
        "sync",
        "--no-dev",
        "--no-editable",
        "--reinstall",
        "--no-install-project",
    ]

    # Pass extras and groups from part config if present.
    for extra in sorted(part_config.get("uv-extras", [])):
        sync_cmd.extend(["--extra", extra])
    for group in sorted(part_config.get("uv-groups", [])):
        sync_cmd.extend(["--group", group])

    env = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(venv_dir),
        "UV_FROZEN": "true",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_COMPILE_BYTECODE": "1",
        "VIRTUAL_ENV": str(venv_dir),
    }

    _run_uv(sync_cmd, cwd=charm_dir, env=env)

    # Clean up venv to match charmcraft's UV plugin behaviour:
    # remove python* binaries and extra scripts, keep only activate.
    keep_bin = {"activate"}
    venv_bin = venv_dir / "bin"
    if venv_bin.is_dir():
        for entry in venv_bin.iterdir():
            if entry.name not in keep_bin:
                entry.unlink()

    venv_lib64 = venv_dir / "lib64"
    if venv_lib64.is_symlink():
        venv_lib64.unlink()

    # The bin/lib64 cleanup above does not touch ``site-packages``, so the
    # ``*.dist-info`` metadata attestation verification reads is still
    # intact when this runs.
    _verify_installed_attestations(venv_dir, strict=verify_attestations)


def process_dump_part(
    charm_dir: pathlib.Path,
    prime_dir: pathlib.Path,
    part_config: dict[str, Any],
) -> None:
    """Process a dump plugin part: copy files with organize/stage/prime rules."""
    source = part_config.get("source", ".")
    source_dir = (charm_dir / source).resolve()

    if not source_dir.is_dir():
        return

    organize: dict[str, str] = part_config.get("organize", {})
    stage_patterns: list[str] = part_config.get("stage", [])
    prime_patterns: list[str] = part_config.get("prime", [])

    # Load jujuignore for filtering dump parts.
    ignore = jujuignore.JujuIgnore.from_file(str(charm_dir / ".jujuignore"))

    for dirpath_str, dirnames, filenames in os.walk(str(source_dir), followlinks=True):
        dirpath = pathlib.Path(dirpath_str)
        rel_dir = dirpath.relative_to(source_dir)

        # Skip ignored directories.
        dirnames[:] = [d for d in dirnames if not ignore.match(str(rel_dir / d), is_dir=True)]

        for filename in filenames:
            rel_path = str(rel_dir / filename)
            if ignore.match(rel_path, is_dir=False):
                continue

            # Apply organize rules (source → dest mapping).
            dest_path = rel_path
            for src_pattern, dst_pattern in organize.items():
                if fnmatch.fnmatch(rel_path, src_pattern):
                    dest_path = dst_pattern
                    break

            # Apply stage fileset filter.
            if stage_patterns and not _match_fileset(dest_path, stage_patterns):
                continue

            # Apply prime fileset filter.
            if prime_patterns and not _match_fileset(dest_path, prime_patterns):
                continue

            src_file = source_dir / rel_path
            dst_file = prime_dir / dest_path
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_file), str(dst_file))


# Patterns we recognise and can handle safely in override-build scripts.
# Each is a compiled regex that matches the full override-build text
# (after stripping and normalising whitespace).
_OVERRIDE_GIT_VERSION = re.compile(
    r"craftctl\s+default\s*\n"
    r"\s*git\s+describe\s+--always\s*>\s*\$CRAFT_PART_INSTALL/version\s*$",
    re.MULTILINE,
)

_OVERRIDE_RUSTUP_DEFAULT = re.compile(
    r"rustup\s+default\s+stable\s*\n\s*craftctl\s+default\s*$",
    re.MULTILINE,
)

_OVERRIDE_CRAFTCTL_ONLY = re.compile(
    r"craftctl\s+default\s*$",
    re.MULTILINE,
)


def _handle_override_build(
    charm_dir: pathlib.Path,
    prime_dir: pathlib.Path,
    part_name: str,
    override: str,
) -> None:
    """Handle recognised override-build patterns.

    Raises ``ValueError`` for unrecognised scripts.
    """
    stripped = override.strip()

    # Pattern 1: craftctl default + git describe --always > version
    if _OVERRIDE_GIT_VERSION.match(stripped):
        result = subprocess.run(
            ["git", "describe", "--always"],
            cwd=str(charm_dir),
            capture_output=True,
            text=True,
        )
        version = result.stdout.strip() if result.returncode == 0 else "unknown"
        (prime_dir / "version").write_text(version + "\n")
        return

    # Pattern 2: rustup default stable + craftctl default
    if _OVERRIDE_RUSTUP_DEFAULT.match(stripped):
        # Just verify Rust is available; the uv sync will use it.
        result = subprocess.run(
            ["rustc", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ValueError(
                f"Part {part_name!r} requires Rust (override-build runs "
                f"'rustup default stable') but rustc is not available."
            )
        return

    # Pattern 3: just craftctl default (possibly with comments).
    # Strip comment lines before matching.
    no_comments = "\n".join(
        line for line in stripped.splitlines() if not line.strip().startswith("#")
    ).strip()
    if _OVERRIDE_CRAFTCTL_ONLY.match(no_comments):
        return

    raise ValueError(
        f"Part {part_name!r} has an override-build that quick pack cannot "
        f"handle safely.  Override content:\n{stripped}"
    )


def process_nil_part(
    part_name: str,
    part_config: dict[str, Any],
) -> None:
    """Process a nil plugin part (no-op).

    The nil plugin does nothing by itself.  If an ``override-build`` is
    present and is not a recognised safe pattern, we raise an error.
    """
    if "override-build" in part_config:
        stripped = part_config["override-build"].strip()
        # Strip comment lines.
        no_comments = "\n".join(
            line for line in stripped.splitlines() if not line.strip().startswith("#")
        ).strip()
        if no_comments and not _OVERRIDE_CRAFTCTL_ONLY.match(no_comments):
            raise ValueError(
                f"Part {part_name!r} (nil plugin) has an override-build that "
                f"quick pack cannot handle safely.  Override content:\n{stripped}"
            )


def process_parts(
    charm_dir: pathlib.Path,
    prime_dir: pathlib.Path,
    project: dict[str, Any],
    *,
    verify_attestations: bool = False,
) -> None:
    """Process all parts defined in the project."""
    parts = project.get("parts", {})

    if not parts:
        raise ValueError(
            "No parts found in charmcraft.yaml.  Quick pack requires at least "
            "one part with plugin: uv."
        )

    # Match the venv's Python to the series the unit will boot — see
    # ``process_uv_part`` for the failure shape when these diverge.  Done
    # once at the top of ``process_parts`` rather than inside the loop so
    # multi-part charms (uv + dump + nil) all see the same value.
    target_python = _metadata.resolve_target_python(project)

    found_uv = False
    for name, part_config in parts.items():
        plugin = part_config.get("plugin", name)

        # Custom build steps (override-build, override-stage, override-prime,
        # override-pull) invoke arbitrary shell.  Quick pack can't safely
        # replicate them — fall back to charmcraft so the custom steps run.
        for override_key in (
            "override-build",
            "override-stage",
            "override-prime",
            "override-pull",
        ):
            if override_key in part_config:
                raise ValueError(
                    f"Quick pack does not support {override_key!r} in part {name!r}; "
                    f"use charmcraft pack instead."
                )

        if plugin == "uv":
            if found_uv:
                raise ValueError("Quick pack supports only one UV plugin part.")
            # Handle override-build before the main UV processing.
            if "override-build" in part_config:
                _handle_override_build(
                    charm_dir,
                    prime_dir,
                    name,
                    part_config["override-build"],
                )
            process_uv_part(
                charm_dir,
                prime_dir,
                part_config,
                verify_attestations=verify_attestations,
                target_python=target_python,
            )
            found_uv = True

        elif plugin == "dump":
            process_dump_part(charm_dir, prime_dir, part_config)

        elif plugin == "nil":
            process_nil_part(name, part_config)

        else:
            raise ValueError(
                f"Quick pack only supports 'uv', 'dump', and 'nil' plugins, "
                f"got {plugin!r} in part {name!r}."
            )

    if not found_uv:
        raise ValueError(
            "Quick pack requires a part with plugin: uv.  Found parts: " + ", ".join(parts.keys())
        )
