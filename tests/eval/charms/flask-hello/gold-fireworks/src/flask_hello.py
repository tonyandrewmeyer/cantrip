"""Functions for managing and interacting with the Flask Hello workload.

This module handles installation, configuration, and lifecycle of the
flask-hello systemd service running inside a virtualenv at /srv/flask-hello/venv.
"""

import logging
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

logger = logging.getLogger(__name__)

APP_DIR = Path("/srv/flask-hello")
VENV_DIR = APP_DIR / "venv"
CONFIG_DIR = Path("/etc/flask-hello")
CONFIG_FILE = CONFIG_DIR / "config.env"
SERVICE_NAME = "flask-hello"
SERVICE_FILE = Path(f"/etc/systemd/system/{SERVICE_NAME}.service")
SYSTEM_APP_DIR = Path("/opt/flask-hello")


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a shell command and log the output."""
    logger.debug("Running: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=True, **kwargs)


def install() -> None:
    """Install the workload: system deps, virtualenv, app code, systemd service."""
    logger.info("Installing flask-hello workload...")

    # Ensure directories exist
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Install system dependencies
    _run(["apt-get", "update"])
    _run(["apt-get", "install", "-y", "python3-venv", "python3-pip", "libpq-dev"])

    # Create virtualenv
    if not VENV_DIR.exists():
        _run(["python3", "-m", "venv", str(VENV_DIR)])

    # Install app dependencies
    pip = VENV_DIR / "bin" / "pip"
    req_file = SYSTEM_APP_DIR / "requirements-app.txt"
    if req_file.exists():
        _run([str(pip), "install", "-r", str(req_file)])
    else:
        logger.warning("Requirements file not found at %s", req_file)

    # Copy app code
    app_src = SYSTEM_APP_DIR / "app.py"
    app_dst = APP_DIR / "app.py"
    if app_src.exists():
        shutil.copy2(str(app_src), str(app_dst))
    else:
        logger.warning("App source not found at %s", app_src)

    # Write systemd service file
    _write_systemd_service()

    # Reload systemd
    _run(["systemctl", "daemon-reload"])

    logger.info("Installation complete.")


def _write_systemd_service() -> None:
    """Write the systemd service unit file."""
    service_content = textwrap.dedent(
        f"""\
        [Unit]
        Description=Flask Hello Web Application
        After=network.target

        [Service]
        Type=simple
        User=root
        Group=root
        WorkingDirectory={APP_DIR}
        EnvironmentFile={CONFIG_FILE}
        ExecStart={VENV_DIR}/bin/gunicorn -w 2 -b 0.0.0.0:5000 app:app
        Restart=on-failure
        RestartSec=5

        [Install]
        WantedBy=multi-user.target
        """
    )
    SERVICE_FILE.write_text(service_content)
    logger.info("Wrote systemd service file to %s", SERVICE_FILE)


def write_config(
    database_url: str | None = None,
    log_level: str = "info",
    debug: bool = False,
    workers: int = 2,
) -> None:
    """Write the environment configuration file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        f"LOG_LEVEL={log_level}",
        f"FLASK_DEBUG={'true' if debug else 'false'}",
        f"WORKERS={workers}",
    ]
    if database_url:
        lines.append(f"DATABASE_URL={database_url}")

    CONFIG_FILE.write_text("\n".join(lines) + "\n")
    logger.info("Wrote config to %s", CONFIG_FILE)

    # Update systemd service with correct worker count
    _update_service_workers(workers)


def _update_service_workers(workers: int) -> None:
    """Update the systemd service file with the correct worker count."""
    if not SERVICE_FILE.exists():
        return
    content = SERVICE_FILE.read_text()
    # Replace the gunicorn worker count
    import re

    new_content = re.sub(
        r"gunicorn -w \d+",
        f"gunicorn -w {workers}",
        content,
    )
    if new_content != content:
        SERVICE_FILE.write_text(new_content)
        _run(["systemctl", "daemon-reload"])
        logger.info("Updated systemd service workers to %d", workers)


def start() -> None:
    """Start the systemd service."""
    logger.info("Starting %s service...", SERVICE_NAME)
    _run(["systemctl", "enable", SERVICE_NAME])
    _run(["systemctl", "start", SERVICE_NAME])


def stop() -> None:
    """Stop the systemd service."""
    logger.info("Stopping %s service...", SERVICE_NAME)
    try:
        _run(["systemctl", "stop", SERVICE_NAME])
    except subprocess.CalledProcessError:
        logger.warning("Service %s was not running.", SERVICE_NAME)


def restart() -> None:
    """Restart the systemd service."""
    logger.info("Restarting %s service...", SERVICE_NAME)
    try:
        _run(["systemctl", "restart", SERVICE_NAME])
    except subprocess.CalledProcessError:
        logger.warning("Failed to restart %s; attempting start instead.", SERVICE_NAME)
        start()


def is_running() -> bool:
    """Check whether the systemd service is active."""
    try:
        result = _run(
            ["systemctl", "is-active", SERVICE_NAME],
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == "active"
    except subprocess.CalledProcessError:
        return False


def get_version() -> str | None:
    """Return a version string for the workload."""
    return "1.0.0"


def reset_database_counter() -> None:
    """Reset the page-view counter in the database."""
    import psycopg2

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE page_views SET count = 0 WHERE id = 1")
        conn.commit()
    finally:
        conn.close()
