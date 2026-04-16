#!/bin/bash
# =============================================================================
# Quickpack Benchmark
# =============================================================================
# Compares quickpack (Rust & Python) against charmcraft pack in various modes.
# Target charm: canonical/self-signed-certificates-operator (uses uv plugin).
#
# Modes tested:
#   1. Quickpack (Rust)       — fast local packing, Rust binary
#   2. Quickpack (Python)     — fast local packing, Python implementation
#   3. charmcraft --destructive (warm) — local build, craft-parts cached
#   4. charmcraft --destructive (cold) — local build, cache cleared
#   5. charmcraft pack (warm LXD)      — LXD build, instance cached
#   6. charmcraft pack (clean LXD)     — LXD build, instance destroyed first
#
# Requirements:
#   - charmcraft 4.x (snap)
#   - LXD (snap, initialised)
#   - uv
#   - Rust quickpack binary built (cargo build --release in src/quickpack-rs/)
#   - Build packages: libffi-dev libssl-dev pkg-config python3-dev python3-venv
#
# Usage:
#   ./run_benchmark.sh [RUNS]     # default: 3 runs per mode
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CANTRIP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORK_DIR="/tmp/quickpack-benchmark"
CHARM_REPO="canonical/self-signed-certificates-operator"
PLATFORM="ubuntu@24.04:amd64"
RUNS="${1:-3}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RESULTS_FILE="$SCRIPT_DIR/results-${TIMESTAMP}.json"
LOG_FILE="$SCRIPT_DIR/benchmark-${TIMESTAMP}.log"

RUST_QUICKPACK="$CANTRIP_ROOT/src/quickpack-rs/target/release/quickpack"
PYTHON_QUICKPACK_CMD="uv run --project $CANTRIP_ROOT python -m quickpack"

# Ensure Rust binary is built.
if [ ! -x "$RUST_QUICKPACK" ]; then
    echo "Building Rust quickpack..."
    (cd "$CANTRIP_ROOT/src/quickpack-rs" && cargo build --release)
fi

# Clone the charm if needed.
mkdir -p "$WORK_DIR"
CHARM_DIR="$WORK_DIR/self-signed-certificates-operator"
if [ ! -d "$CHARM_DIR" ]; then
    echo "Cloning $CHARM_REPO..."
    gh repo clone "$CHARM_REPO" "$CHARM_DIR" -- --depth=1
fi

COMPARE_DIR="$WORK_DIR/compare"
OUTPUT_DIR="$WORK_DIR/output"
mkdir -p "$COMPARE_DIR" "$OUTPUT_DIR"

# Logging helper.
log() {
    echo "$@" | tee -a "$LOG_FILE"
}

time_cmd() {
    local start end
    start=$(date +%s%N)
    eval "$@" >> "$LOG_FILE" 2>&1
    local rc=$?
    end=$(date +%s%N)
    echo "scale=3; ($end - $start) / 1000000000" | bc
    return $rc
}

extract_and_fingerprint() {
    local charm_file="$1" label="$2"
    local dir="$COMPARE_DIR/$label"
    rm -rf "$dir"
    mkdir -p "$dir"
    unzip -qo "$charm_file" -d "$dir"

    log "=== $label charm ==="
    find "$dir" -type f | sed "s|$dir/||" | grep -v __pycache__ | sort > "$dir.filelist"
    log "  Files: $(wc -l < "$dir.filelist")"
    log "  Size:  $(du -h "$charm_file" | cut -f1)"

    if [ -d "$dir/src" ]; then
        local src_hash
        src_hash=$(find "$dir/src" -type f | sort | xargs md5sum | md5sum | cut -d' ' -f1)
        log "  src/ hash: $src_hash"
    fi

    local sp_count
    sp_count=$(find "$dir/venv" -path "*/site-packages/*" -name "*.py" 2>/dev/null | wc -l)
    log "  Python files in venv: $sp_count"
    log ""
}

run_n_times() {
    local label="$1" cmd="$2" n="$3"
    local -a times=()

    log ">>> $label ($n runs)"
    for i in $(seq 1 "$n"); do
        t=$(time_cmd "$cmd")
        times+=("$t")
        log "  Run $i: ${t}s"
    done

    local best
    best=$(printf '%s\n' "${times[@]}" | sort -n | head -1)
    local median
    median=$(printf '%s\n' "${times[@]}" | sort -n | sed -n "$((($n + 1) / 2))p")
    log "  Best:   ${best}s"
    log "  Median: ${median}s"
    log ""

    # Return values via global variables (bash limitation).
    _BEST="$best"
    _MEDIAN="$median"
    _ALL="$(IFS=,; echo "${times[*]}")"
}

# =============================================================================
log "============================================================"
log "Quickpack Benchmark — $(date)"
log "Charm:    $CHARM_REPO"
log "Platform: $PLATFORM"
log "Runs:     $RUNS per mode"
log "============================================================"
log ""

# Clean state for quickpack.
rm -rf "$CHARM_DIR/venv"

# --- 1. Rust quickpack ---
run_n_times "Quickpack (Rust)" \
    "rm -f '$OUTPUT_DIR'/*.charm && '$RUST_QUICKPACK' '$CHARM_DIR' --output-dir '$OUTPUT_DIR' --quiet" \
    "$RUNS"
RUST_BEST="$_BEST"; RUST_MEDIAN="$_MEDIAN"; RUST_ALL="$_ALL"
cp "$OUTPUT_DIR"/*.charm "$COMPARE_DIR/rust.charm" 2>/dev/null || true

# --- 2. Python quickpack ---
run_n_times "Quickpack (Python)" \
    "rm -f '$OUTPUT_DIR'/*.charm && $PYTHON_QUICKPACK_CMD '$CHARM_DIR' --output-dir '$OUTPUT_DIR' --quiet" \
    "$RUNS"
PYTHON_BEST="$_BEST"; PYTHON_MEDIAN="$_MEDIAN"; PYTHON_ALL="$_ALL"
cp "$OUTPUT_DIR"/*.charm "$COMPARE_DIR/python.charm" 2>/dev/null || true

# --- 3. charmcraft --destructive-mode (warm — craft-parts cached) ---
# charmcraft must run from within the charm directory to avoid cross-device
# link errors (it writes parts/ relative to cwd).
# First, do a throw-away cold build to populate the craft-parts cache.
log ">>> Warming craft-parts cache for destructive mode..."
sudo rm -f "$CHARM_DIR"/*.charm
(cd "$CHARM_DIR" && sudo charmcraft pack --destructive-mode --platform "$PLATFORM") >> "$LOG_FILE" 2>&1 || true

run_n_times "charmcraft --destructive (warm)" \
    "sudo rm -f '$CHARM_DIR'/*.charm && cd '$CHARM_DIR' && sudo charmcraft pack --destructive-mode --platform '$PLATFORM'" \
    "$RUNS"
DESTR_WARM_BEST="$_BEST"; DESTR_WARM_MEDIAN="$_MEDIAN"; DESTR_WARM_ALL="$_ALL"
cp "$CHARM_DIR"/*.charm "$COMPARE_DIR/destructive_warm.charm" 2>/dev/null || true

# --- 4. charmcraft --destructive-mode (cold — cache cleared) ---
run_n_times "charmcraft --destructive (cold)" \
    "sudo rm -rf '$CHARM_DIR/parts' '$CHARM_DIR'/*.charm && cd '$CHARM_DIR' && sudo charmcraft pack --destructive-mode --platform '$PLATFORM'" \
    "$RUNS"
DESTR_COLD_BEST="$_BEST"; DESTR_COLD_MEDIAN="$_MEDIAN"; DESTR_COLD_ALL="$_ALL"
cp "$CHARM_DIR"/*.charm "$COMPARE_DIR/destructive_cold.charm" 2>/dev/null || true

# --- 5. charmcraft pack (warm LXD — instance and image cached) ---
log ">>> Warming LXD cache..."
rm -f "$CHARM_DIR"/*.charm
(cd "$CHARM_DIR" && charmcraft pack --platform "$PLATFORM") >> "$LOG_FILE" 2>&1 || true

run_n_times "charmcraft pack (warm LXD)" \
    "rm -f '$CHARM_DIR'/*.charm && cd '$CHARM_DIR' && charmcraft pack --platform '$PLATFORM'" \
    "$RUNS"
LXD_WARM_BEST="$_BEST"; LXD_WARM_MEDIAN="$_MEDIAN"; LXD_WARM_ALL="$_ALL"
cp "$CHARM_DIR"/*.charm "$COMPARE_DIR/lxd_warm.charm" 2>/dev/null || true

# --- 6. charmcraft pack (cold LXD — charmcraft clean, image re-downloaded) ---
# ``charmcraft clean`` removes both the instance AND the cached buildd base
# image, forcing a full image download + instance setup on next pack.
# This simulates a CI system running for the first time.
run_n_times "charmcraft pack (cold LXD)" \
    "rm -f '$CHARM_DIR'/*.charm && cd '$CHARM_DIR' && charmcraft clean --platform '$PLATFORM' 2>/dev/null; charmcraft pack --platform '$PLATFORM'" \
    "$RUNS"
LXD_CLEAN_BEST="$_BEST"; LXD_CLEAN_MEDIAN="$_MEDIAN"; LXD_CLEAN_ALL="$_ALL"
cp "$CHARM_DIR"/*.charm "$COMPARE_DIR/lxd_clean.charm" 2>/dev/null || true

# =============================================================================
# Charm content comparison
# =============================================================================
log "============================================================"
log "CHARM CONTENT COMPARISON"
log "============================================================"
for label in rust python destructive_warm destructive_cold lxd_warm lxd_clean; do
    charm_file="$COMPARE_DIR/$label.charm"
    if [ -f "$charm_file" ]; then
        extract_and_fingerprint "$charm_file" "$label"
    fi
done

log "--- File list diffs (vs charmcraft destructive_warm as reference) ---"
for label in rust python lxd_warm lxd_clean; do
    if [ -f "$COMPARE_DIR/$label.filelist" ] && [ -f "$COMPARE_DIR/destructive_warm.filelist" ]; then
        diff_count=$(diff "$COMPARE_DIR/destructive_warm.filelist" "$COMPARE_DIR/$label.filelist" | grep -c "^[<>]" || true)
        log "  $label vs destructive_warm: $diff_count file differences"
        if [ "$diff_count" -gt 0 ] && [ "$diff_count" -lt 30 ]; then
            diff "$COMPARE_DIR/destructive_warm.filelist" "$COMPARE_DIR/$label.filelist" | head -30 | sed 's/^/    /' >> "$LOG_FILE"
        fi
    fi
done
log ""

# =============================================================================
# Summary
# =============================================================================
log "============================================================"
log "RESULTS — best of $RUNS runs"
log "============================================================"
printf "%-35s %10s %10s\n" "Mode" "Best" "Median" | tee -a "$LOG_FILE"
printf "%-35s %10s %10s\n" "-----------------------------------" "----------" "----------" | tee -a "$LOG_FILE"
printf "%-35s %9ss %9ss\n" "Quickpack (Rust)" "$RUST_BEST" "$RUST_MEDIAN" | tee -a "$LOG_FILE"
printf "%-35s %9ss %9ss\n" "Quickpack (Python)" "$PYTHON_BEST" "$PYTHON_MEDIAN" | tee -a "$LOG_FILE"
printf "%-35s %9ss %9ss\n" "charmcraft --destructive (warm)" "$DESTR_WARM_BEST" "$DESTR_WARM_MEDIAN" | tee -a "$LOG_FILE"
printf "%-35s %9ss %9ss\n" "charmcraft --destructive (cold)" "$DESTR_COLD_BEST" "$DESTR_COLD_MEDIAN" | tee -a "$LOG_FILE"
printf "%-35s %9ss %9ss\n" "charmcraft pack (warm LXD)" "$LXD_WARM_BEST" "$LXD_WARM_MEDIAN" | tee -a "$LOG_FILE"
printf "%-35s %9ss %9ss\n" "charmcraft pack (clean LXD)" "$LXD_CLEAN_BEST" "$LXD_CLEAN_MEDIAN" | tee -a "$LOG_FILE"
log ""

# Speedup vs clean LXD.
log "--- Speedup vs charmcraft pack (clean LXD) ---"
printf "%-35s %5sx\n" "Quickpack (Rust)" "$(echo "scale=0; $LXD_CLEAN_BEST / $RUST_BEST" | bc)" | tee -a "$LOG_FILE"
printf "%-35s %5sx\n" "Quickpack (Python)" "$(echo "scale=0; $LXD_CLEAN_BEST / $PYTHON_BEST" | bc)" | tee -a "$LOG_FILE"
printf "%-35s %5sx\n" "charmcraft --destructive (warm)" "$(echo "scale=0; $LXD_CLEAN_BEST / $DESTR_WARM_BEST" | bc)" | tee -a "$LOG_FILE"
printf "%-35s %5sx\n" "charmcraft --destructive (cold)" "$(echo "scale=0; $LXD_CLEAN_BEST / $DESTR_COLD_BEST" | bc)" | tee -a "$LOG_FILE"
printf "%-35s %5sx\n" "charmcraft pack (warm LXD)" "$(echo "scale=0; $LXD_CLEAN_BEST / $LXD_WARM_BEST" | bc)" | tee -a "$LOG_FILE"
log ""

# Write JSON results.
cat > "$RESULTS_FILE" << ENDJSON
{
  "charm": "self-signed-certificates-operator",
  "repo": "$CHARM_REPO",
  "platform": "$PLATFORM",
  "runs": $RUNS,
  "timestamp": "$TIMESTAMP",
  "charmcraft_version": "$(charmcraft version 2>/dev/null || echo unknown)",
  "results": {
    "rust_quickpack": {
      "best": $RUST_BEST,
      "median": $RUST_MEDIAN,
      "all": [$RUST_ALL]
    },
    "python_quickpack": {
      "best": $PYTHON_BEST,
      "median": $PYTHON_MEDIAN,
      "all": [$PYTHON_ALL]
    },
    "charmcraft_destructive_warm": {
      "best": $DESTR_WARM_BEST,
      "median": $DESTR_WARM_MEDIAN,
      "all": [$DESTR_WARM_ALL]
    },
    "charmcraft_destructive_cold": {
      "best": $DESTR_COLD_BEST,
      "median": $DESTR_COLD_MEDIAN,
      "all": [$DESTR_COLD_ALL]
    },
    "charmcraft_lxd_warm": {
      "best": $LXD_WARM_BEST,
      "median": $LXD_WARM_MEDIAN,
      "all": [$LXD_WARM_ALL]
    },
    "charmcraft_lxd_clean": {
      "best": $LXD_CLEAN_BEST,
      "median": $LXD_CLEAN_MEDIAN,
      "all": [$LXD_CLEAN_ALL]
    }
  }
}
ENDJSON

log "Results: $RESULTS_FILE"
log "Full log: $LOG_FILE"
log "Done."
