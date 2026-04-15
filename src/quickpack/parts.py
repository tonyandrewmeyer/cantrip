"""Parts processing for quick pack.

Supports ``uv`` and ``dump`` plugins only.
"""

import fnmatch
import os
import pathlib
import shutil
import subprocess
from typing import Any

from quickpack import jujuignore


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


def process_uv_part(
    charm_dir: pathlib.Path,
    prime_dir: pathlib.Path,
    part_config: dict[str, Any],
) -> None:
    """Process a UV plugin part: copy src/lib and install deps.

    The UV plugin only copies ``src/`` and ``lib/`` from the project
    (not the full tree), then installs Python dependencies into ``venv/``.
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

    subprocess.run(
        [
            "uv",
            "venv",
            "--relocatable",
            "--python",
            "python3",
            str(venv_dir),
        ],
        cwd=str(charm_dir),
        check=True,
        capture_output=True,
        text=True,
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

    subprocess.run(
        sync_cmd,
        cwd=str(charm_dir),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    # Clean up venv to match charmcraft's UV plugin behaviour:
    # remove python* binaries and extra scripts, keep only activate.
    _KEEP_BIN = {"activate"}
    venv_bin = venv_dir / "bin"
    if venv_bin.is_dir():
        for entry in venv_bin.iterdir():
            if entry.name not in _KEEP_BIN:
                entry.unlink()

    venv_lib64 = venv_dir / "lib64"
    if venv_lib64.is_symlink():
        venv_lib64.unlink()


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


def process_parts(
    charm_dir: pathlib.Path,
    prime_dir: pathlib.Path,
    project: dict[str, Any],
) -> None:
    """Process all parts defined in the project."""
    parts = project.get("parts", {})

    if not parts:
        raise ValueError(
            "No parts found in charmcraft.yaml.  Quick pack requires at least "
            "one part with plugin: uv."
        )

    found_uv = False
    for name, part_config in parts.items():
        plugin = part_config.get("plugin", name)

        if plugin == "uv":
            if found_uv:
                raise ValueError("Quick pack supports only one UV plugin part.")
            process_uv_part(charm_dir, prime_dir, part_config)
            found_uv = True

        elif plugin == "dump":
            process_dump_part(charm_dir, prime_dir, part_config)

        else:
            raise ValueError(
                f"Quick pack only supports 'uv' and 'dump' plugins, "
                f"got {plugin!r} in part {name!r}."
            )

    if not found_uv:
        raise ValueError(
            "Quick pack requires a part with plugin: uv.  Found parts: " + ", ".join(parts.keys())
        )
