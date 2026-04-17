---
name: security-review
description: Charm-specific security review to run before a BUILD task finishes
---

# Security Review

Run this review on every charm you write before finishing a BUILD task.  The
goal is to catch the common charm-specific security issues — not a full OWASP
audit.  Report findings inline in the subagent output; apply HIGH-confidence
fixes yourself, surface HIGH-confidence findings for the user, and silently
fix MEDIUM ones when the fix is obvious.

## How to use

1. List every Python file you wrote or modified in this task.
2. For each file, walk the checks below.  Most files only need 30 seconds.
3. If you find an issue, fix it or record it in the output with file:line,
   severity, evidence, and the fix you applied.
4. Only declare the task complete once HIGH-confidence issues are resolved.

## Confidence gating

- **HIGH** — shell concatenation with user input, secrets written to debug
  logs, credentials in `config.yaml` rather than Juju secrets.  Fix before
  finishing.
- **MEDIUM** — unbounded `subprocess.run` without timeout, missing
  `str.format` validation, broad `except Exception`.  Fix silently if the
  change is a one-liner; otherwise note it.
- **LOW** — stylistic concerns, hypothetical attacker models.  Do not report.

If you cannot reach HIGH confidence on a finding, drop it.  Noisy reports
teach the user to ignore you.

## Checks

### 1. Shell injection in subprocess calls

Charms shell out to `juju-*` binaries, `pebble`, `openssl`, workload
processes, and helpers.  Every call is a potential injection site if any
argument comes from a relation bag, config, action param, or environment.

- **Bad:** `subprocess.run(f"pebble exec -- run-migration {user_input}", shell=True)`
- **Good:** `subprocess.run(["pebble", "exec", "--", "run-migration", user_input], check=True)`

Checklist:
- [ ] No `shell=True` anywhere unless the command is entirely literal.
- [ ] Every `subprocess.run` uses a list of arguments, not a string.
- [ ] No `os.system`, `os.popen`, or `commands.getoutput`.
- [ ] `shlex.split()` is **not** a sanitiser — it just tokenises.  Don't rely on it.

### 2. Path traversal in file operations

Many charms accept config values that become file paths (log dirs, cert
paths, plugin paths).  Treat any path derived from config, relation data, or
action params as attacker-controlled.

- Reject absolute paths unless the charm explicitly owns that location.
- Reject `..` components.
- Use `pathlib.Path(base).resolve()` and verify the result is still inside
  the intended base with `Path.is_relative_to()`.

### 3. Secrets handled via Juju secrets, not config

Any sensitive value (password, token, API key, TLS key) must go through
Juju secrets — never a plain config option.

- [ ] `charmcraft.yaml` config options do not contain `password`, `token`,
  `key`, `secret`, or similar.
- [ ] Secrets are obtained via `self.model.get_secret(...)` or passed
  through a relation as a secret URI.
- [ ] Secret content is never written to `logger.info/debug`, exceptions,
  or status messages.  Use IDs or the phrase "[redacted]".

### 4. Relation data trust boundary

Relation data is **remote-controlled** from the perspective of the charm.
Validate before use; never feed straight into the filesystem, shell, or
template engines.

- [ ] Numeric fields are parsed with `int()` / `float()` inside a
  `try/except`.
- [ ] String fields that become file paths, URLs, or commands are
  validated against an allowlist or regex.
- [ ] Databag size is bounded.  Don't copy a 10 MB blob into your local
  state because the peer sent it.

### 5. SSRF in HTTP calls

If the charm fetches URLs that come from config, relation data, or a
workload response, treat them as attacker-controlled.

- Validate scheme is `http`/`https`.
- Reject private/internal addresses (`127.0.0.1`, `169.254.169.254`,
  `::1`, `fc00::/7`, RFC1918) unless the charm explicitly talks to them.
- Always set a connect timeout and a read timeout.

### 6. Broad exception handling

`except Exception:` hides security-relevant failures.  Especially
dangerous in secret-rotation, TLS-renewal, and auth paths, where swallowing
an error can leave the charm running on stale credentials.

- Catch specific exceptions.  If the fallback is truly "give up and go to
  BlockedStatus", that's fine — but log the exception type and message.
- Never `except:` (bare).

### 7. Deserialisation

- Use `yaml.safe_load`, never `yaml.load`.
- Use `json.loads` with a size limit for relation data.
- Never `pickle.load` untrusted data.  Juju has no mechanism that
  legitimately needs pickled payloads in 2026.

### 8. Logging hygiene

- Secrets and tokens are never logged (see §3).
- Relation-data dumps in logs should be keys only, not full values.
- Debug logs must not contain PII even from test fixtures.

### 9. Template injection (rare, but check)

If the charm writes workload configs by string-formatting user input
into templates (nginx.conf, haproxy.cfg, pg_hba.conf), use a template
engine with autoescaping or validate the input against a strict regex.
Never `f"""{cfg}"""`-format a multi-line config.

### 10. TLS and certificate handling

- [ ] `verify=False` / `ssl.CERT_NONE` never appear.
- [ ] Certificate files written with `chmod 0o400` / `0o600`, not world-readable.
- [ ] Certs rotated on the `certificate-available` event, not on a timer.

## Output format

When you report findings, use this structure so the user can skim them:

```
[security-review] <N> HIGH finding(s), <M> MEDIUM fixed silently

HIGH: src/charm.py:142 — shell=True with config-derived arg
  Evidence: subprocess.run(f"migrate {self.config['db-url']}", shell=True)
  Fix: passed args as list; removed shell=True
```

If there are zero HIGH findings and you fixed zero MEDIUM silently, print:

```
[security-review] no findings
```

## When to skip

Skip this skill for:
- Trivial edits (renaming, docstring-only changes).
- RESEARCH or DEBUG tasks (apply on BUILD only).
- Generated scaffolding (charmcraft init output before you edit it).

Otherwise, always run it.  A missed security bug that reaches Charmhub is
much more expensive than 30 seconds of your time.
