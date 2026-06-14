#!/usr/bin/env bash
# Stage every $HOME-side input each clip script depends on.
#
# Run once before re-recording any clip on a fresh machine:
#
#   demos/recordings/_bootstrap.sh
#
# Idempotent — re-running it overwrites nothing already correct, and
# only refreshes content that has drifted.

set -euo pipefail
REPO=$(git rev-parse --show-toplevel)

# ----------------------------------------------------------------------
# Common minimal-charm scaffold.  Used by cli-demo, tui-demo, web-demo.
# ----------------------------------------------------------------------
write_minimal_charm() {
    local name=$1 dir=$2 summary=$3
    mkdir -p "$dir/src"
    cat > "$dir/charmcraft.yaml" <<EOF
name: $name
type: charm
summary: $summary
base: ubuntu@24.04
build-base: ubuntu@24.04
platforms: {amd64: null}
parts:
  charm:
    plugin: uv
    source: .
EOF
    cat > "$dir/pyproject.toml" <<EOF
[project]
name = "$name"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["ops>=3,<4"]
EOF
    cat > "$dir/src/charm.py" <<'EOF'
import ops

class Charm(ops.CharmBase):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)

if __name__ == "__main__":
    ops.main(Charm)
EOF
}

# cli-demo / tui-demo / web-demo — minimal scaffolds for the
# print-mode, TUI and Web UI clips.
write_minimal_charm cli-demo "$HOME/cli-demo" "Demo charm shown in the cantrip CLI marketing clip."
write_minimal_charm tui-demo "$HOME/tui-demo" "Demo charm shown in the cantrip TUI marketing clip."
write_minimal_charm web-demo "$HOME/web-demo" "Demo charm shown in the cantrip Web UI marketing clip."

# ----------------------------------------------------------------------
# broken-charm — deliberately incomplete charm for the --improve clip.
# Carries enough surface (a config option declared but never read,
# a Pebble layer, no tests, no observability) to trigger every
# headline charmlint category.
# ----------------------------------------------------------------------
mkdir -p "$HOME/broken-charm/src"
cat > "$HOME/broken-charm/charmcraft.yaml" <<'EOF'
name: broken-demo
type: charm
summary: A small charm with deliberate gaps for the cantrip --improve demo.

base: ubuntu@24.04
build-base: ubuntu@24.04
platforms:
  amd64:

parts:
  charm:
    plugin: uv
    source: .

containers:
  app:
    resource: app-image

resources:
  app-image:
    type: oci-image
    description: A simple demo workload.

config:
  options:
    log-level:
      type: string
      default: info
      description: Log level for the workload.
EOF
cat > "$HOME/broken-charm/pyproject.toml" <<'EOF'
[project]
name = "broken-demo"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["ops>=3,<4"]
EOF
cat > "$HOME/broken-charm/src/charm.py" <<'EOF'
"""A deliberately incomplete charm for the cantrip --improve demo."""
import ops


class BrokenDemoCharm(ops.CharmBase):
    """No status handling, no tracing, no metrics, no tests, no docs."""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on["app"].pebble_ready, self._on_pebble_ready)

    def _on_install(self, _: ops.InstallEvent) -> None:
        self.unit.status = ops.ActiveStatus()

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        layer = ops.pebble.Layer({
            "summary": "demo layer",
            "services": {
                "app": {
                    "override": "replace",
                    "command": "/bin/sleep infinity",
                    "startup": "enabled",
                }
            },
        })
        event.workload.add_layer("app", layer, combine=True)
        event.workload.replan()


if __name__ == "__main__":
    ops.main(BrokenDemoCharm)
EOF

# ----------------------------------------------------------------------
# ntfy-charm — empty target for the from-scratch hero recording.
# ----------------------------------------------------------------------
mkdir -p "$HOME/ntfy-charm"

# ----------------------------------------------------------------------
# sample-charm — a real session transcript copied off this machine for
# the transcript-export clip.  Skipped if the source isn't present;
# the user can drop any .cantrip session into $HOME/sample-charm/.cantrip
# manually as a fallback.
# ----------------------------------------------------------------------
mkdir -p "$HOME/sample-charm"
SOURCE=
for cand in "$HOME/tempo-k8s-operator/.cantrip" "$REPO/.cantrip"; do
    if [ -f "$cand" ]; then
        SOURCE=$cand
        break
    fi
done
if [ -n "$SOURCE" ] && [ ! -f "$HOME/sample-charm/.cantrip" ]; then
    # SQLite WAL fails on 9p / multipass mounts — copy via sqlite's own
    # backup API rather than `cp` so the transferred file is consistent.
    if python3 - "$SOURCE" "$HOME/sample-charm/.cantrip" <<'PY' 2>/tmp/_bootstrap-sqlite.err
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
src.close(); dst.close()
PY
    then
        echo "Staged sample-charm/.cantrip from $SOURCE"
    else
        echo "Note: copying $SOURCE failed (likely a 9p / multipass mount" >&2
        echo "      where SQLite WAL is unreliable).  Try running this from" >&2
        echo "      a native filesystem, or drop a .cantrip session into" >&2
        echo "      $HOME/sample-charm/.cantrip manually." >&2
    fi
elif [ -z "$SOURCE" ]; then
    echo "Note: no source .cantrip session found — drop one into $HOME/sample-charm/.cantrip" >&2
    echo "      to enable the transcript-export clip." >&2
fi

# ----------------------------------------------------------------------
# qp-demo — staged in-repo charm used by the quickpack clip.  Already
# under version control at demos/recordings/_assets/qp-demo/; no work
# to do here, just confirm the lockfile.
# ----------------------------------------------------------------------
if [ ! -f "$REPO/demos/recordings/_assets/qp-demo/uv.lock" ]; then
    (cd "$REPO/demos/recordings/_assets/qp-demo" && uv lock) || true
fi

echo "Bootstrap complete."
