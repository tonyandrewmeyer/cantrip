"""Seed workspaces for the live charm-build e2e suite.

Each constant below is a ``{relative_path: contents}`` map consumed by
``harness.seed_workspace``.  The apps are deliberately minimal so that
rockcraft and charmcraft builds stay quick — the goal of the e2e suite
is to exercise the agent's build/deploy flow, not to demonstrate a
realistic application.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------

_FLASK_APP = """\
from flask import Flask

app = Flask(__name__)


@app.route("/")
def index():
    return {"status": "ok", "service": "flask-demo"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
"""

FLASK: dict[str, str] = {
    "app.py": _FLASK_APP,
    "requirements.txt": "flask>=3.0\n",
}


# ---------------------------------------------------------------------------
# Django
# ---------------------------------------------------------------------------
#
# The django-framework extension expects a WSGI entry point and a
# manage.py — exactly what ``django-admin startproject`` would emit.
# We inline the smallest possible project rather than invoking
# django-admin so that this seed has no external dependency.


_DJANGO_MANAGE = """\
#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "djangodemo.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
"""

_DJANGO_SETTINGS = """\
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "demo-not-a-real-secret"
DEBUG = False
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
]
MIDDLEWARE: list[str] = []
ROOT_URLCONF = "djangodemo.urls"
TEMPLATES: list[dict] = []
WSGI_APPLICATION = "djangodemo.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    },
}
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
"""

_DJANGO_URLS = """\
from django.http import JsonResponse
from django.urls import path


def index(_request):
    return JsonResponse({"status": "ok", "service": "django-demo"})


urlpatterns = [path("", index)]
"""

_DJANGO_WSGI = """\
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "djangodemo.settings")
application = get_wsgi_application()
"""

DJANGO: dict[str, str] = {
    "manage.py": _DJANGO_MANAGE,
    "requirements.txt": "Django>=5.0,<6.0\n",
    "djangodemo/__init__.py": "",
    "djangodemo/settings.py": _DJANGO_SETTINGS,
    "djangodemo/urls.py": _DJANGO_URLS,
    "djangodemo/wsgi.py": _DJANGO_WSGI,
}


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------

_FASTAPI_APP = """\
from fastapi import FastAPI

app = FastAPI(title="fastapi-demo")


@app.get("/")
def index():
    return {"status": "ok", "service": "fastapi-demo"}
"""

FASTAPI: dict[str, str] = {
    "app.py": _FASTAPI_APP,
    "requirements.txt": "fastapi>=0.115\nuvicorn>=0.30\n",
}


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------
#
# The go-framework profile needs a go.mod and a main.go.  We do not build
# this with rockcraft in the e2e test — the agent is told to deploy with
# a pre-built public OCI image — so the content here only has to satisfy
# ``analyse_framework`` and ``charmcraft init``.

_GO_MAIN = """\
package main

import (
\t"encoding/json"
\t"net/http"
)

func main() {
\thttp.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
\t\tw.Header().Set("Content-Type", "application/json")
\t\t_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
\t})
\t_ = http.ListenAndServe(":8000", nil)
}
"""

_GO_MOD = """\
module go-demo

go 1.22
"""

GO: dict[str, str] = {
    "main.go": _GO_MAIN,
    "go.mod": _GO_MOD,
}


# ---------------------------------------------------------------------------
# Machine charm workload
# ---------------------------------------------------------------------------
#
# The machine profile has no framework extension — the scaffold is a
# blank ops charm.  Including a systemd .service file plus a trivial
# shell workload ensures ``analyse_framework`` picks up the "machine"
# substrate hint, which is what we want the test to exercise.

_HELLO_SH = """\
#!/bin/sh
echo "hello from the machine charm demo"
sleep 3600
"""

_HELLO_SERVICE = """\
[Unit]
Description=Hello machine-charm demo
After=network.target

[Service]
ExecStart=/usr/local/bin/hello.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""

_HELLO_README = """\
# hello-machine

A placeholder workload for exercising the machine-charm build path.
The charm wraps the ``hello.service`` systemd unit.
"""

MACHINE: dict[str, str] = {
    "README.md": _HELLO_README,
    "systemd/hello.service": _HELLO_SERVICE,
    "bin/hello.sh": _HELLO_SH,
}
