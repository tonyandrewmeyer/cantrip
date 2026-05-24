---
name: charm-development-commands
description: Standardised tox/make/just command names for charm projects — format, lint, unit, integration, docs
globs: [tox.ini, Makefile, justfile, pyproject.toml, CONTRIBUTING.md, HACKING.md]
---

# Charm Development Commands

Charms must provide a consistent, minimal set of named commands for
formatting, linting, type checking, and testing.  This makes it
easier to work across charming teams and enables ecosystem-wide
compatibility testing.  Based on Canonical spec OP061.

> Adapted from the `charm-development-commands` skill in
> `tonyandrewmeyer/charming-with-claude`, CC BY 4.0 (Tony Meyer, 2025).
> Reformatted for cantrip's bundled-skill frontmatter; content
> otherwise unchanged.  See Provenance at the foot of this skill for
> the source link.

## Required commands

| Command | Definition |
|---------|-----------|
| *(no args)* | Running the tool with no arguments must execute the `lint` and `unit` commands |
| `format` | Automatically format code (including tests) according to project style |
| `lint` | Report linting errors (ruff, pylint, flake8, isort, pydocstyle, bandit, etc.) **and** static type checking issues (pyright, ty, mypy).  Must include Charmhub hosted charm libraries that this charm provides, if any; should include test code |
| `unit` | Run unit tests for the charm and its libs.  Includes both deprecated Harness and state-transition (Scenario) framework tests |
| `integration` | Run integration tests against a real Juju controller.  Includes pytest-operator, python-libjuju, and Jubilant tests |
| `docs` | Build documentation (if docs are in the repository).  Should run `make run` in the docs directory |

**Note**: use `format` (not the Go-style `fmt`) — this has been the
charmcraft profile standard and aligns with other full-word commands.

## Optional commands

Charms may include additional commands as needed:

- Lib-specific commands (e.g. `static-lib`).
- Combined commands (e.g. `static` = `static-charm` + `static-lib`).
- Aliases (e.g. `fmt` as alias for `format`).
- `functional` tests — validate workload interactions without Juju (especially for machine charms).

## Command runners

Commands must be run with one of these tools:

| Tool | Examples |
|------|---------|
| **tox** | `tox`, `tox -e lint`, `tox -e unit -- -k test_foo` |
| **make** | `make`, `make lint`, `make unit ARGS='-k test_foo'` |
| **just** | `just`, `just lint`, `just unit` |

The most highly recommended runner is the one used in charmcraft
profiles — `tox` at present.  Commands must work **without
additional arguments**.

## Monorepo conventions

For repositories containing more than one charm:

- `format`, `lint`, `unit`, `integration` must be available in **each charm folder**.
- `format` should be available at the **top level**, formatting all charms.
- `lint` is ideally at the top level (may need to run per-charm for conflicting dependencies).
- `unit` and `integration` are ideally at the top level, running all tests.
- `docs`: at the top level if one set of docs; in each charm folder if separate docs.

## Documentation

Requirements for running commands (e.g. installing `uv` or `tox`)
must be clearly documented in a **CONTRIBUTING** or **HACKING** file
at the top level of the repository.

## Provenance

Adapted from [the `charm-development-commands` skill](https://github.com/tonyandrewmeyer/charming-with-claude/tree/main/skills/charm-development-commands)
in [`tonyandrewmeyer/charming-with-claude`](https://github.com/tonyandrewmeyer/charming-with-claude),
CC BY 4.0 (Tony Meyer, 2025).  Content reformatted for cantrip's
bundled-skill frontmatter; otherwise unchanged.
