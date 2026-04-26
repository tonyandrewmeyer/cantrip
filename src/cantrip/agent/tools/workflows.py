"""Secure-by-default GitHub Actions workflow generation for charms.

Used by ``CharmcraftInitTool`` as a post-init injection step.  Generates
``.github/workflows/`` and ``.github/dependabot.yml`` following the supply-chain
practices applied to Cantrip itself: full-commit-SHA action pins, empty
workflow-level permissions broadened per-job, ``persist-credentials: false`` on
every checkout, a zizmor audit step, and Dependabot with cooldowns.
"""

import pathlib

# Pinned action SHAs — kept in sync with Cantrip's own workflows.  Dependabot
# in the generated charm keeps these fresh after scaffolding.
_ACTION_CHECKOUT = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6"
_ACTION_SETUP_UV = "astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57  # v8"
_ACTION_UPLOAD_SARIF = (
    "github/codeql-action/upload-sarif@c10b8064de6f491fea524254123dbe5e09572f13  # v4"
)
_ACTION_DEPENDENCY_REVIEW = (
    "actions/dependency-review-action@2031cfc080254a8a887f58cffee85186f0e49e48  # v4.9.0"
)


_CI_WORKFLOW = f"""\
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

# Workflow-level permissions are empty; each job grants only what it needs.
permissions: {{}}

jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: {_ACTION_CHECKOUT}
        with:
          persist-credentials: false

      - name: Install uv
        uses: {_ACTION_SETUP_UV}

      - name: Install tox
        run: uv tool install tox --with tox-uv

      - name: Run lint
        run: tox -e lint

      - name: Run format check
        run: tox -e format -- --check
        continue-on-error: true

  unit:
    name: Unit tests
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: {_ACTION_CHECKOUT}
        with:
          persist-credentials: false

      - name: Install uv
        uses: {_ACTION_SETUP_UV}

      - name: Install tox
        run: uv tool install tox --with tox-uv

      - name: Run unit tests
        run: tox -e unit

  pack:
    name: Pack
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: {_ACTION_CHECKOUT}
        with:
          persist-credentials: false

      - name: Install charmcraft
        run: sudo snap install charmcraft --classic

      - name: Pack charm
        run: charmcraft pack --destructive-mode
"""


_SECURITY_WORKFLOW = f"""\
name: Security

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions: {{}}

jobs:
  zizmor:
    name: Workflow Security
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: {_ACTION_CHECKOUT}
        with:
          persist-credentials: false

      - name: Install uv
        uses: {_ACTION_SETUP_UV}

      - name: Run zizmor
        run: uv tool run zizmor --format sarif . > results.sarif
        continue-on-error: true

      - name: Upload SARIF
        uses: {_ACTION_UPLOAD_SARIF}
        if: always()
        continue-on-error: true
        with:
          sarif_file: results.sarif
          category: zizmor

  dependency-review:
    name: Dependency Review
    runs-on: ubuntu-latest
    permissions:
      contents: read
    if: github.event_name == 'pull_request'
    steps:
      - uses: {_ACTION_CHECKOUT}
        with:
          persist-credentials: false

      - name: Dependency Review
        uses: {_ACTION_DEPENDENCY_REVIEW}
"""


# Uses ``workflow_dispatch`` so a human must explicitly trigger a release, and
# a ``charmhub`` deployment environment so the repo can require manual approval
# and isolate the Charmhub token.  Tag creation happens only after a successful
# upload, via the GitHub API (no persisted checkout credentials needed).
_RELEASE_WORKFLOW = f"""\
name: Release

on:
  workflow_dispatch:
    inputs:
      version:
        description: Semantic version (without leading v), e.g. 1.2.3
        required: true
        type: string
      channel:
        description: Charmhub channel, e.g. latest/edge or latest/stable
        required: true
        default: latest/edge
        type: string

permissions: {{}}

jobs:
  release:
    name: Upload to Charmhub
    runs-on: ubuntu-latest
    environment: charmhub
    permissions:
      contents: write
    steps:
      - uses: {_ACTION_CHECKOUT}
        with:
          persist-credentials: false

      - name: Install charmcraft
        run: sudo snap install charmcraft --classic

      - name: Pack charm
        run: charmcraft pack --destructive-mode

      - name: Upload to Charmhub
        env:
          CHARMCRAFT_AUTH: ${{{{ secrets.CHARMHUB_TOKEN }}}}
          CHANNEL: ${{{{ inputs.channel }}}}
        run: |
          charm_file=$(ls *.charm | head -n1)
          charmcraft upload "$charm_file" --release="$CHANNEL"

      - name: Create tag and release
        env:
          GH_TOKEN: ${{{{ github.token }}}}
          VERSION: ${{{{ inputs.version }}}}
          REPO: ${{{{ github.repository }}}}
          SHA: ${{{{ github.sha }}}}
        run: |
          gh api "/repos/$REPO/git/refs" \\
            -X POST \\
            -f "ref=refs/tags/v$VERSION" \\
            -f "sha=$SHA"
          gh release create "v$VERSION" \\
            --generate-notes \\
            --title "v$VERSION"
"""


_DEPENDABOT_CONFIG = """\
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
      day: monday
    cooldown:
      default-days: 14
      semver-major-days: 14
      semver-minor-days: 14
      semver-patch-days: 14
    groups:
      python-dependencies:
        patterns:
          - "*"
        update-types:
          - minor
          - patch
    open-pull-requests-limit: 10
    labels:
      - dependencies
      - python
    commit-message:
      prefix: "chore(deps)"

  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
      day: monday
    cooldown:
      default-days: 14
    groups:
      github-actions:
        patterns:
          - "*"
    labels:
      - dependencies
      - github-actions
    commit-message:
      prefix: "chore(deps)"
"""


# Written to ``SECURITY.md`` in the charm root.  Documents the recommended
# branch/tag rulesets that protect the release flow.  Rulesets are configured
# via the GitHub UI or API (there is no canonical in-repo file format for
# them), so we document rather than generate configuration.
_SECURITY_MD = """\
# Security

## Reporting a vulnerability

Please report security issues privately via GitHub Security Advisories rather
than opening a public issue.

## Supply-chain posture

This charm is built and released with the following protections.  If you fork
this repository, replicate the corresponding rulesets on your own copy.

### Workflows

All GitHub Actions are pinned to full commit SHAs (not floating tags).  The
default workflow-level permissions are empty (`permissions: {}`) and broadened
per-job only where needed.  Every `actions/checkout` step uses
`persist-credentials: false`.  A [zizmor][zizmor] audit runs on every push and
pull request.

Releases use a `workflow_dispatch` trigger and run inside a dedicated
`charmhub` deployment environment that requires manual approval and scopes the
`CHARMHUB_TOKEN` secret to release runs only.  The release workflow creates a
git tag and GitHub release only after the Charmhub upload succeeds.

### Recommended repository rulesets

Configure these in *Settings → Rules → Rulesets*:

- **main branch** — require pull request reviews; disallow force-push;
  disallow deletion; require status checks (`CI / *`, `Security / *`) to pass.
- **tags `v*`** — restrict tag creation to the `release` workflow identity
  (`GITHUB_REF_NAME` equals the workflow run); disallow deletion; disallow
  force-push.

### Dependencies

Python and GitHub Actions dependencies are tracked by Dependabot with a 14-day
cooldown on all version ranges to reduce exposure to compromised releases.
New charm dependencies should be justified in the design; prefer the standard
library where feasible, and avoid dependencies that pull in native binaries
unless the workload genuinely requires them.

[zizmor]: https://docs.zizmor.sh/
"""


def inject_github_workflows(target_path: pathlib.Path, charm_name: str) -> list[str]:
    """Scaffold ``.github/workflows/``, Dependabot, and ``SECURITY.md``.

    Existing files are left untouched so a caller who re-runs
    ``charmcraft init`` against an already-scaffolded charm (or who has
    hand-edited any of these files) does not have their changes clobbered.

    Returns human-readable descriptions of what was done.
    """
    actions: list[str] = []
    workflows_dir = target_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    files: list[tuple[pathlib.Path, str, str]] = [
        (workflows_dir / "ci.yaml", _CI_WORKFLOW, "CI workflow"),
        (workflows_dir / "security.yaml", _SECURITY_WORKFLOW, "security workflow"),
        (workflows_dir / "release.yaml", _RELEASE_WORKFLOW, "release workflow"),
        (
            target_path / ".github" / "dependabot.yml",
            _DEPENDABOT_CONFIG,
            "Dependabot config",
        ),
        (target_path / "SECURITY.md", _SECURITY_MD, "SECURITY.md"),
    ]

    for path, content, label in files:
        if path.exists():
            actions.append(f"{label} already exists at {path.name} — skipped")
            continue
        path.write_text(content)
        actions.append(f"Created {label} at {path.relative_to(target_path)}")

    # Unused for now — reserved so the signature can grow if per-charm
    # substitution is needed later (e.g. custom Python version).
    _ = charm_name
    return actions
