---
name: operational-readiness
description: Charm operational-readiness features — status, health, pause/resume, backup/restore, diagnostics, upgrades, certs, secret rotation
---

# Operational Readiness

This skill covers implementing production-ready operational features in Juju charms, aligned with Canonical's Operational Readiness Metrics. Use this skill when filling gaps identified by the `operational_readiness` tool.

## Status Reporting Patterns

The charm must set informative status for every expected condition so operators never see a generic "active" when something is wrong.

### Required Status Conditions

Use `ops.StatusBase` subclasses with **actionable messages** — the operator should know what to do from reading the status alone.

```python
# Missing required configuration.
if not self.config.get("database-uri"):
    self.unit.status = ops.BlockedStatus("Set 'database-uri' config to continue")
    return

# Missing relation.
if not self.model.get_relation("database"):
    self.unit.status = ops.BlockedStatus("Integrate with a database: juju integrate <app> postgresql")
    return

# Waiting for relation data.
if not relation.data[relation.app].get("connection-string"):
    self.unit.status = ops.WaitingStatus("Waiting for database credentials")
    return

# Upstream unreachable.
if not self._check_upstream_health():
    self.unit.status = ops.BlockedStatus("Cannot reach upstream service at {uri}")
    return

# Paused.
if self._is_paused():
    self.unit.status = ops.MaintenanceStatus("Paused — run 'resume' action to restart")
    return

# Upgrade in progress.
if self._upgrading:
    self.unit.status = ops.MaintenanceStatus("Upgrade in progress")
    return

# All good.
self.unit.status = ops.ActiveStatus()
```

### Reconciliation Pattern

Put status-setting logic in a single `_reconcile()` method called from every event handler:

```python
def _reconcile(self) -> None:
    """Single source of truth for unit status."""
    # Check conditions in priority order (most severe first).
    ...
```

## Health-Check Action

Implement a `get-health` action that validates the charm and workload are functioning correctly.

```python
def _on_get_health(self, event: ops.ActionEvent) -> None:
    """Run comprehensive health checks and return structured results."""
    checks = {}

    # 1. Core processes running.
    container = self.unit.get_container("workload")
    try:
        services = container.get_services()
        checks["processes"] = all(
            svc.is_running() for svc in services.values()
        )
    except ops.pebble.ConnectionError:
        checks["processes"] = False

    # 2. API responsiveness (if applicable).
    try:
        resp = httpx.get(f"http://localhost:{self._port}/health", timeout=5)
        checks["api"] = resp.status_code == 200
    except httpx.HTTPError:
        checks["api"] = False

    # 3. Required relations connected.
    checks["relations"] = all(
        self.model.get_relation(ep) is not None
        for ep in self._required_endpoints
    )

    # 4. Certificate validity (if TLS).
    if self._tls_enabled:
        checks["certificates"] = self._check_cert_validity()

    healthy = all(checks.values())
    event.set_results({
        "healthy": healthy,
        "checks": checks,
    })
    if not healthy:
        event.fail(f"Unhealthy: {[k for k, v in checks.items() if not v]}")
```

## Pause and Resume Actions

Gracefully stop and restart workload services without data loss.

```python
def _on_pause(self, event: ops.ActionEvent) -> None:
    """Gracefully pause workload services."""
    container = self.unit.get_container("workload")
    try:
        container.stop("workload")
    except ops.pebble.ChangeError as e:
        event.fail(f"Failed to pause: {e}")
        return
    self._paused = True
    self.unit.status = ops.MaintenanceStatus("Paused — run 'resume' action to restart")
    event.set_results({"status": "paused"})

def _on_resume(self, event: ops.ActionEvent) -> None:
    """Resume paused workload services."""
    container = self.unit.get_container("workload")
    try:
        container.start("workload")
    except ops.pebble.ChangeError as e:
        event.fail(f"Failed to resume: {e}")
        return
    self._paused = False
    self._reconcile()
    event.set_results({"status": "resumed"})
```

**Key points:**
- Always update status after pause/resume.
- Store paused state so `_reconcile()` can report it.
- The charm should remain paused across hook executions (use peer data or Juju secrets to persist the flag).

## Backup and Restore Actions

For stateful charms, implement `create-backup`, `list-backups`, and `restore-backup`.

```python
def _on_create_backup(self, event: ops.ActionEvent) -> None:
    """Create a backup using workload-native tools."""
    container = self.unit.get_container("workload")
    timestamp = datetime.datetime.now(tz=datetime.UTC).strftime("%Y%m%d-%H%M%S")
    backup_path = f"/backups/{self.app.name}-{timestamp}.tar.gz"

    # Delegate to workload-native backup tool.
    process = container.exec(
        ["pg_dump", "-Fc", "-f", backup_path],
        environment=self._db_env(),
    )
    try:
        process.wait_output()
    except ops.pebble.ExecError as e:
        event.fail(f"Backup failed: {e.stderr}")
        return

    event.set_results({
        "backup-id": timestamp,
        "path": backup_path,
        "status": "completed",
    })
```

**Key points:**
- Use workload-native tools (pg_dump, mysqldump, redis-cli BGSAVE, etc.).
- Include timestamp in backup identifiers.
- `list-backups` should return available backups with timestamps and sizes.
- `restore-backup` should accept a backup ID and warn about data replacement.
- Consider encryption for sensitive data.

## Diagnostics Bundle Action

Collect sanitised operational data for troubleshooting.

```python
def _on_collect_diagnostics(self, event: ops.ActionEvent) -> None:
    """Collect sanitised diagnostics bundle."""
    bundle = {}

    # 1. Charm config (scrub secrets).
    safe_config = {}
    for key, value in self.config.items():
        if any(s in key.lower() for s in ("password", "secret", "token", "key")):
            safe_config[key] = "***REDACTED***"
        else:
            safe_config[key] = str(value)
    bundle["config"] = safe_config

    # 2. Unit status.
    bundle["status"] = str(self.unit.status)

    # 3. Relation data (scrub credentials).
    bundle["relations"] = self._collect_relation_summary()

    # 4. Container service status.
    container = self.unit.get_container("workload")
    try:
        services = container.get_services()
        bundle["services"] = {
            name: {"running": svc.is_running(), "current": svc.current.value}
            for name, svc in services.items()
        }
    except ops.pebble.ConnectionError:
        bundle["services"] = "pebble not ready"

    # 5. Recent logs (last 100 lines, scrubbed).
    bundle["logs"] = self._collect_scrubbed_logs(container, lines=100)

    event.set_results({"diagnostics": json.dumps(bundle, indent=2)})
```

**Key points:**
- Always scrub secrets, IP addresses, and certificates from output.
- Include container service status, relation summaries, and recent logs.
- Keep the bundle concise — operators need signal, not noise.

## Upgrade Pre-Flight Checks

Verify the environment is ready for an upgrade before proceeding.

```python
def _on_pre_upgrade_check(self, event: ops.ActionEvent) -> None:
    """Run pre-upgrade validation checks."""
    issues = []

    # 1. Version compatibility.
    current = self._get_workload_version()
    target = event.params.get("target-version", "latest")
    if not self._versions_compatible(current, target):
        issues.append(f"Cannot upgrade from {current} to {target}")

    # 2. Cluster health (for clustered workloads).
    if not self._check_cluster_healthy():
        issues.append("Cluster is not healthy — fix before upgrading")

    # 3. Recent backup exists.
    if not self._has_recent_backup(max_age_hours=24):
        issues.append("No backup in the last 24 hours — create one first")

    # 4. Sufficient resources.
    if not self._check_resources():
        issues.append("Insufficient disk space for upgrade")

    if issues:
        event.set_results({"ready": False, "issues": issues})
        event.fail(f"Pre-upgrade check failed: {len(issues)} issue(s)")
    else:
        event.set_results({"ready": True, "issues": []})
```

## Certificate Management

For charms using TLS, provide actions to view and regenerate certificates.

```python
def _on_get_certificate(self, event: ops.ActionEvent) -> None:
    """Show current certificate details."""
    cert_path = self._cert_path()
    if not cert_path.exists():
        event.fail("No certificate found")
        return

    # Parse certificate for summary (not the private key!).
    import cryptography.x509
    cert = cryptography.x509.load_pem_x509_certificate(cert_path.read_bytes())
    event.set_results({
        "subject": str(cert.subject),
        "issuer": str(cert.issuer),
        "not-before": str(cert.not_valid_before_utc),
        "not-after": str(cert.not_valid_after_utc),
        "serial": str(cert.serial_number),
    })
```

## Secret Rotation

Use Juju secrets instead of plain-text config for credentials.

```python
# Store a secret.
secret = self.app.add_secret({"password": generated_password})
secret.grant(relation)

# Retrieve a secret.
secret = self.model.get_secret(label="db-credentials")
content = secret.get_content()
password = content["password"]

# Handle rotation.
def _on_secret_rotate(self, event: ops.SecretRotateEvent) -> None:
    new_password = self._generate_password()
    event.secret.set_content({"password": new_password})
```

**Key points:**
- Never store passwords, tokens, or API keys in charm config.
- Use `self.app.add_secret()` for application-level secrets.
- Handle `secret-rotate` events for automatic rotation.
- Grant secrets to specific relations, not globally.
