# Cantrip marketing recordings

Short-form clips for the marketing site, one per Cantrip mode of
operation plus the deterministic helper tools.  Each clip is paired
with the script that produced it, so any clip can be re-recorded:
the script is the source of truth and the cast/GIF beside it is the
artefact.

| File | Mode | Length | Format | Source |
|------|------|--------|--------|--------|
| [`charmlint.cast`](charmlint.cast) | CLI tool | ~30 s | asciicast | [`charmlint.sh`](charmlint.sh) |
| [`quickpack.cast`](quickpack.cast) | CLI tool | ~40 s | asciicast | [`quickpack.sh`](quickpack.sh) |
| [`transcript-export.cast`](transcript-export.cast) | CLI tool | ~55 s | asciicast | [`transcript-export.sh`](transcript-export.sh) |
| [`improve.cast`](improve.cast) | `--improve` audit | ~50 s | asciicast | [`improve.sh`](improve.sh) |
| [`cli.cast`](cli.cast) | `--print` headless | ~75 s | asciicast | [`cli.sh`](cli.sh) |
| [`tui.gif`](tui.gif) | TUI | ~12 s | GIF (VHS) | [`tui.tape`](tui.tape) |
| [`tui-popups.gif`](tui-popups.gif) | TUI — slash + ``@`` autocomplete + help | ~25 s | GIF (VHS) | [`tui-popups.tape`](tui-popups.tape) |
| [`tui-shell-mode.gif`](tui-shell-mode.gif) | TUI — ``Ctrl-X`` shell mode | ~25 s | GIF (VHS) | [`tui-shell-mode.tape`](tui-shell-mode.tape) |
| [`tui-plan-mode.gif`](tui-plan-mode.gif) | TUI — ``/plan`` read-only gate | ~25 s | GIF (VHS) | [`tui-plan-mode.tape`](tui-plan-mode.tape) |
| [`tui-yolo-mode.gif`](tui-yolo-mode.gif) | TUI — ``--yolo`` confirmations off | ~22 s | GIF (VHS) | [`tui-yolo-mode.tape`](tui-yolo-mode.tape) |
| [`tui-pause-resume.gif`](tui-pause-resume.gif) | TUI — ``/pause`` and ``/resume`` lifecycle | ~25 s | GIF (VHS) | [`tui-pause-resume.tape`](tui-pause-resume.tape) |
| [`tui-feelings.gif`](tui-feelings.gif) | TUI — ``/feelings`` parliament against a real charm | ~50 s | GIF (VHS) | [`tui-feelings.tape`](tui-feelings.tape) |
| [`web.gif`](web.gif) | `--web` | ~28 s | GIF (Playwright) | [`web.sh`](web.sh) + [`_web_driver.py`](_web_driver.py) |
| [`hero-ntfy.cast`](hero-ntfy.cast) | `--no-tui` interactive | ~3 min 10 s (factor 2 from a 6 min 20 s raw capture) | asciicast | [`hero-ntfy.sh`](hero-ntfy.sh) |
| [`hero-ntfy-raw.cast`](hero-ntfy-raw.cast) | (raw capture, source for re-edits) | ~6 min 20 s | asciicast | (kept alongside hero-ntfy.cast) |

The marketing site embeds asciicasts via [asciinema-player][asciin]
and GIFs inline.  Casts are scrubable text — the JS player handles
playback speed, copy-paste, and resize without re-encoding.

[asciin]: https://github.com/asciinema/asciinema-player

## Running a clip locally

```bash
# Replay any cast file in your terminal.
uvx asciinema play demos/recordings/<name>.cast
```

## Re-recording a clip

Each `*.sh` (asciicast) or `*.tape` / `*.sh` (VHS / Playwright) is
self-contained and reproducible.  They depend on staged inputs under
[`_assets/`](_assets/) and on six side directories the clips read
from `$HOME` (kept outside the cantrip checkout because SQLite WAL
fails on the 9p / multipass mount that some authoring environments
use):

```
$HOME/sample-charm/      # transcript-export — copied from a real session
$HOME/cli-demo/          # cli.sh / cli.cast — minimal scaffold charm
$HOME/tui-demo/          # tui.tape — minimal scaffold charm
$HOME/web-demo/          # web.sh / web.gif — minimal scaffold charm
$HOME/broken-charm/      # improve.sh — deliberately incomplete charm
$HOME/ntfy-charm/        # hero-ntfy.sh — empty target for the from-scratch build
```

Run the bootstrap once to create them on a fresh machine:

```bash
demos/recordings/_bootstrap.sh
```

To re-record a single clip — run the script from the cantrip repo
root so its `git rev-parse --show-toplevel` resolves correctly:

```bash
# asciicast clips — drive a shell script under asciinema rec.
TERM=xterm-256color uvx asciinema rec --overwrite \
    --cols 110 --rows 30 --idle-time-limit 2 \
    --command demos/recordings/charmlint.sh \
    demos/recordings/charmlint.cast

# TUI GIF — render a VHS .tape.  Needs ffmpeg + ttyd on $PATH.
~/go/bin/vhs demos/recordings/tui.tape

# Web GIF — start the cantrip web server, drive Playwright, convert webm to gif.
demos/recordings/web.sh
```

## Why two formats

Asciicasts are the right shape for terminal output: small, scrubable,
copy-and-paste-able.  The TUI clip and the Web clip are GIFs because:

- **TUI**: Driving a Textual app over a pseudo-terminal with `pexpect`
  proved brittle — the slash-command popup eats keystrokes if you race
  it, and `\r` doesn't always reach the input widget.  VHS owns its
  own `ttyd`-backed terminal with frame-clocked rendering, which is
  what makes the recording deterministic.
- **Web**: Playwright records its browser context as WebM video.  GIF
  is the embed-anywhere fallback; the source `*.webm` is also kept
  if higher quality is needed.

## Hero clip — scope and speed-up workflow

`hero-ntfy.cast` captures the **research → synthesis → design**
phase of a from-scratch ntfy build.  The build/deploy/test
continuation is best driven from the TUI today: print and CLI
modes don't yet auto-resolve the design-confirmation gate the
agent inserts after synthesis.

The post-processing pipeline:

```bash
# 1. Capture (long-running — kick off in background).
demos/recordings/hero-ntfy.sh

# 2. Trim trailing rate-limit / retry cruft to land cleanly on the
#    design proposal (the natural endpoint of the cast).  The raw
#    capture is preserved as hero-ntfy-raw.cast.
#    [Trimming is a one-line python edit — see the script header.]

# 3. Scale every event timestamp and cap idle gaps so dead air from
#    LLM thinking compresses cleanly.  Asciicasts are JSONL — the
#    first line is metadata; the rest are [t_seconds, "o", "data"].
demos/recordings/_speedup.py demos/recordings/hero-ntfy-raw.cast \
    demos/recordings/hero-ntfy.cast --factor 2.0 --idle-cap 0.3
```

The `_speedup.py` helper is destructive only on its output — the
raw cast stays intact for re-edits.
