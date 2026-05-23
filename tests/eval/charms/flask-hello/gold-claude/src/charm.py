#!/usr/bin/env python3
"""Flask Hello machine charm — Path B custom application."""

import logging
import pathlib
import subprocess
import typing

import ops

logger = logging.getLogger(__name__)

_APP_DIR = pathlib.Path("/srv/flask-hello")
_VENV_DIR = _APP_DIR / "venv"
_CONFIG_DIR = pathlib.Path("/etc/flask-hello")
_CONFIG_ENV = _CONFIG_DIR / "config.env"
_SERVICE = "flask-hello"
_PORT = 5000

_SYSTEMD_UNIT = """\
[Unit]
Description=Flask Hello web application
After=network.target

[Service]
EnvironmentFile=/etc/flask-hello/config.env
ExecStart={venv}/bin/gunicorn \\
  --bind 0.0.0.0:{port} \\
  --workers {workers} \\
  --log-level {log_level} \\
  app:app
WorkingDirectory=/srv/flask-hello
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
"""


class FlaskHelloCharm(ops.CharmBase):
    """Charm for the Flask Hello custom web application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on["postgresql"].relation_changed, self._on_postgresql_changed)
        self.framework.observe(self.on["postgresql"].relation_broken, self._on_postgresql_broken)
        self.framework.observe(self.on["nginx-route"].relation_joined, self._on_nginx_joined)
        self.framework.observe(self.on.reset_counter_action, self._on_reset_counter)

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install system dependencies and the Flask app inside a virtualenv."""
        self.unit.status = ops.MaintenanceStatus("installing dependencies")
        try:
            subprocess.run(
                ["apt-get", "install", "-y", "python3-venv", "python3-pip", "nginx"],
                check=True,
                capture_output=True,
            )
            _APP_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["python3", "-m", "venv", str(_VENV_DIR)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [str(_VENV_DIR / "bin" / "pip"), "install", "flask", "gunicorn", "psycopg2-binary"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.error("install failed: %s", exc.stderr)
            self.unit.status = ops.BlockedStatus("install failed — check juju debug-log")
            return

        self._install_systemd_unit()
        self.unit.open_port("tcp", _PORT)
        self.unit.status = ops.MaintenanceStatus("waiting for relations")

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Regenerate config and reload the service."""
        if not self._database_url():
            self.unit.status = ops.BlockedStatus("waiting for postgresql relation")
            return
        self._write_config()
        self._restart_service()

    def _on_postgresql_changed(self, event: ops.RelationChangedEvent) -> None:
        """Start or reconfigure the service once the database is available."""
        if not self._database_url():
            self.unit.status = ops.WaitingStatus("waiting for database credentials")
            return
        self._write_config()
        self._restart_service()

    def _on_postgresql_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Stop the service and block when the database relation is removed."""
        try:
            subprocess.run(["systemctl", "stop", _SERVICE], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            pass
        self.unit.status = ops.BlockedStatus("waiting for postgresql relation")

    def _on_nginx_joined(self, event: ops.RelationJoinedEvent) -> None:
        """Publish the application's upstream address to nginx."""
        if not self.unit.is_leader():
            return
        addr = self._bind_address()
        event.relation.data[self.app].update(
            {
                "service-hostname": self.app.name,
                "service-port": str(_PORT),
                "service-name": self.app.name,
            }
        )
        logger.info("published nginx-route data for %s:%s", addr, _PORT)

    def _on_reset_counter(self, event: ops.ActionEvent) -> None:
        """Execute a SQL statement to reset the page-view counter."""
        db_url = self._database_url()
        if not db_url:
            event.fail("No database relation available.")
            return
        try:
            result = subprocess.run(
                [
                    str(_VENV_DIR / "bin" / "python"),
                    "-c",
                    (
                        "import psycopg2, os; "
                        "conn = psycopg2.connect(os.environ['DATABASE_URL']); "
                        "conn.autocommit = True; "
                        "conn.cursor().execute('UPDATE counters SET count = 0'); "
                        "conn.close(); print('counter reset')"
                    ),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                env={"DATABASE_URL": db_url},
            )
            event.set_results({"result": result.stdout.strip()})
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            event.fail(f"Reset failed: {exc}")

    # -----------------------------------------------------------------
    # Configuration helpers
    # -----------------------------------------------------------------

    def _write_config(self) -> None:
        """Write /etc/flask-hello/config.env from charm config and relations."""
        db_url = self._database_url() or ""
        log_level = typing.cast(str, self.config.get("log-level", "info"))
        debug = typing.cast(bool, self.config.get("debug", False))

        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG_ENV.write_text(
            "\n".join(
                [
                    f"DATABASE_URL={db_url}",
                    f"FLASK_LOG_LEVEL={log_level}",
                    f"FLASK_DEBUG={'1' if debug else '0'}",
                    "",
                ]
            )
        )

    def _install_systemd_unit(self) -> None:
        """Write and enable the systemd unit for the Flask app."""
        workers = typing.cast(int, self.config.get("workers", 2))
        log_level = typing.cast(str, self.config.get("log-level", "info"))
        unit_content = _SYSTEMD_UNIT.format(
            venv=_VENV_DIR,
            port=_PORT,
            workers=workers,
            log_level=log_level,
        )
        unit_path = pathlib.Path(f"/etc/systemd/system/{_SERVICE}.service")
        unit_path.write_text(unit_content)
        subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
        subprocess.run(["systemctl", "enable", _SERVICE], check=True, capture_output=True)

    def _restart_service(self) -> None:
        """Reload systemd config and restart the Flask service."""
        try:
            subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
            subprocess.run(["systemctl", "restart", _SERVICE], check=True, capture_output=True)
            self.unit.status = ops.ActiveStatus()
        except subprocess.CalledProcessError as exc:
            logger.error("service restart failed: %s", exc.stderr)
            self.unit.status = ops.BlockedStatus("flask-hello failed to start")

    # -----------------------------------------------------------------
    # Relation helpers
    # -----------------------------------------------------------------

    def _database_url(self) -> str | None:
        """Build a PostgreSQL connection URL from the postgresql relation."""
        rel = self.model.get_relation("postgresql")
        if rel is None:
            return None
        data = rel.data.get(rel.app)
        if not data:
            return None
        endpoints = data.get("endpoints", "")
        username = data.get("username", "")
        password = data.get("password", "")
        database = data.get("database", "")
        if not all([endpoints, username, password, database]):
            return None
        host_port = endpoints.split(",")[0]
        return f"postgresql://{username}:{password}@{host_port}/{database}"

    def _bind_address(self) -> str:
        """Return this unit's network bind address."""
        binding = self.model.get_binding("nginx-route")
        if binding is None:
            return "127.0.0.1"
        return str(binding.network.bind_address)


if __name__ == "__main__":
    ops.main(FlaskHelloCharm)
