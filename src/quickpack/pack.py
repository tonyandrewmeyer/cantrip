"""Core packing logic — builds a ``.charm`` file from a charm project."""

import os
import pathlib
import tempfile
import zipfile

import yaml

from quickpack import metadata as _metadata
from quickpack import parts as _parts

# The modern dispatch template (from charmcraft's dispatch.py).
# Creates venv/bin/python on first run if missing, sets PYTHONPATH and
# LD_LIBRARY_PATH, then execs the charm entrypoint.
_DISPATCH_TEMPLATE = """\
#!/bin/sh
dispatch_path="$(dirname $(realpath $0))"
venv_bin_path="${{dispatch_path}}/venv/bin"
python_path="${{venv_bin_path}}/python"
if [ ! -e "${{python_path}}" ]; then
    mkdir -p "${{venv_bin_path}}"
    ln -s $(which python3) "${{python_path}}"
fi

export PYTHONPATH="${{dispatch_path}}/lib:${{dispatch_path}}/src"
export LD_LIBRARY_PATH="${{dispatch_path}}/usr/lib:${{dispatch_path}}/lib:${{dispatch_path}}/usr/lib/$(uname -m)-linux-gnu"

exec "${{python_path}}" "${{dispatch_path}}/{entrypoint}"
"""

# Entries that should always be in .jujuignore so that both quick pack
# and regular charmcraft pack skip them.
_REQUIRED_IGNORES = ["*.charm", ".cantrip"]


def _ensure_jujuignore(charm_dir: pathlib.Path) -> None:
    """Ensure ``.jujuignore`` contains our required entries."""
    path = charm_dir / ".jujuignore"
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")

    missing = [entry for entry in _REQUIRED_IGNORES if entry not in existing]
    if missing:
        with path.open("a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            for entry in missing:
                fh.write(entry + "\n")


def _write_dispatch(prime_dir: pathlib.Path, entrypoint: str) -> None:
    """Write the ``dispatch`` script into the prime directory."""
    dispatch = prime_dir / "dispatch"
    dispatch.write_text(_DISPATCH_TEMPLATE.format(entrypoint=entrypoint))
    dispatch.chmod(0o755)


def _build_zip(zip_path: pathlib.Path, prime_dir: pathlib.Path) -> None:
    """Create a ``.charm`` ZIP archive from the prime directory."""
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath_str, _dirnames, filenames in os.walk(str(prime_dir), followlinks=True):
            for filename in filenames:
                file_path = pathlib.Path(dirpath_str) / filename
                arcname = str(file_path.relative_to(prime_dir))
                zf.write(str(file_path), arcname)


def quick_pack(
    charm_dir: str | pathlib.Path,
    *,
    output_dir: str | pathlib.Path | None = None,
) -> pathlib.Path:
    """Pack a charm directory into a ``.charm`` file.

    This is a fast, local-only alternative to ``charmcraft pack`` that
    supports the ``uv`` and ``dump`` plugins.  It skips LXD builds,
    linting, and analysis — producing a valid charm suitable for
    development deploys and upgrade testing.

    Args:
        charm_dir: Path to the charm project directory.
        output_dir: Where to write the ``.charm`` file.  Defaults to
            *charm_dir*.

    Returns:
        Path to the created ``.charm`` file.
    """
    charm_dir = pathlib.Path(charm_dir).resolve()
    output_dir = charm_dir if output_dir is None else pathlib.Path(output_dir).resolve()

    project = _metadata.parse_charmcraft_yaml(charm_dir)
    entrypoint = _metadata.resolve_entrypoint(project)
    arch = _metadata.local_arch()

    _ensure_jujuignore(charm_dir)

    with tempfile.TemporaryDirectory(prefix="quickpack-") as tmp:
        prime_dir = pathlib.Path(tmp) / "prime"
        prime_dir.mkdir()

        # Process parts (uv deps + dump file copies).
        _parts.process_parts(charm_dir, prime_dir, project)

        # Generate dispatch script.
        _write_dispatch(prime_dir, entrypoint)

        # Generate metadata.yaml.
        meta = _metadata.generate_metadata(project)
        with (prime_dir / "metadata.yaml").open("w", encoding="utf-8") as fh:
            yaml.safe_dump(meta, fh, default_flow_style=False)

        # Generate manifest.yaml.
        manifest = _metadata.generate_manifest(project, arch=arch)
        with (prime_dir / "manifest.yaml").open("w", encoding="utf-8") as fh:
            yaml.safe_dump(manifest, fh, default_flow_style=False)

        # Write optional actions.yaml and config.yaml.
        _metadata.write_optional_yaml(project, "actions", "actions.yaml", charm_dir, prime_dir)
        _metadata.write_optional_yaml(project, "config", "config.yaml", charm_dir, prime_dir)

        # Create the .charm zip.
        filename = _metadata.charm_filename(project, arch=arch)
        charm_path = output_dir / filename
        output_dir.mkdir(parents=True, exist_ok=True)
        _build_zip(charm_path, prime_dir)

    return charm_path
