---
name: twelve-factor
description: End-to-end workflow for building 12-factor PaaS charms with rockcraft and charmcraft
---

# 12-Factor PaaS Charm Workflow

This skill covers the complete workflow for building a Juju charm from a 12-factor web application. These charms use the **paas-charm** base — you run `charmcraft init` and `rockcraft init` with a framework profile, customise the generated YAML, build a rock, push it to a registry, pack the charm, and deploy.

## Framework-to-Profile Mapping

| Framework | Charmcraft Profile | Rockcraft Profile | Experimental? |
|-----------|-------------------|-------------------|---------------|
| Flask | `flask-framework` | `flask-framework` | No |
| Django | `django-framework` | `django-framework` | No |
| FastAPI | `fastapi-framework` | `fastapi-framework` | Yes |
| Go | `go-framework` | `go-framework` | Yes |
| Express | `express-framework` | `express-framework` | Yes |
| Spring Boot | `spring-boot-framework` | `spring-boot-framework` | No |

**Experimental** means you must set `ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true` in the environment when running `rockcraft init` or `rockcraft pack` for that profile.

## Step-by-Step Workflow

### 1. Analyse the Application

Use the `analyse_framework` tool to detect the framework and language. The tool returns a `profile` field you can pass directly to `charmcraft_init` and `rockcraft_init`.

### 2. Initialise the Charm

```bash
charmcraft init --profile=flask-framework --name=my-app
```

Use the `charmcraft_init` tool with the detected profile. This creates `charmcraft.yaml`, `src/charm.py`, and test scaffolding tuned for the framework.

### 3. Initialise the Rock

```bash
rockcraft init --profile=flask-framework
```

Use the `rockcraft_init` tool. For Go, Express, and FastAPI profiles, the tool automatically sets the experimental extensions flag.

The generated `rockcraft.yaml` defines how the application is packed into an OCI image (a "rock").

### 4. Customise YAML Files

**rockcraft.yaml** — typical edits:
- Set `name`, `version`, `summary`, `description`
- Add system packages under `stage-packages` if the workload needs them
- Adjust `platforms` (default is `amd64`)

**charmcraft.yaml** — typical edits:
- Set `title`, `summary`, `description`
- Add `requires` relations (database, tracing, logging)
- Add `config.options` for environment variables
- Add `resources` for the OCI image:

```yaml
resources:
  oci-image:
    type: oci-image
    description: OCI image for the application
```

### 5. Build the Rock

```bash
rockcraft pack
```

Use the `rockcraft_pack` tool. This builds the OCI image as a `.rock` file. The first build downloads the Ubuntu base and may take several minutes.

### 6. Push to a Container Registry

```bash
skopeo copy --insecure-policy --dest-tls-verify=false \
  oci-archive:my-app_0.1_amd64.rock \
  docker://localhost:32000/my-app:latest
```

Use the `skopeo_registry_push` tool. The default registry is `localhost:32000` — the MicroK8s built-in registry.

### 7. Pack the Charm

```bash
charmcraft pack
```

Use the `charmcraft_pack` tool. This produces a `.charm` file ready for deployment.

### 8. Deploy with Resources

```bash
juju deploy ./my-app_amd64.charm \
  --resource oci-image=localhost:32000/my-app:latest
```

Use the `juju_deploy` tool with `resources={"oci-image": "localhost:32000/my-app:latest"}`. For charms that access cloud APIs (e.g. ingress), also pass `trust=True`.

### 9. Verify

```bash
juju status --watch 5s
```

Use the `juju_status` tool. The application should reach `active/idle` within a couple of minutes. If it stays in `waiting` or `blocked`, check the status message and logs.

## Database Integration (PostgreSQL)

Most 12-factor apps need a database. The paas-charm profiles support PostgreSQL via a standard `requires` relation.

Add to `charmcraft.yaml`:

```yaml
requires:
  postgresql:
    interface: postgresql_client
    optional: true
```

Deploy and relate:

```bash
juju deploy postgresql-k8s --trust
juju integrate my-app:postgresql postgresql-k8s:database
```

The framework automatically exposes database connection details as environment variables (`POSTGRESQL_DB_CONNECT_STRING`, etc.).

## Ingress

To expose the application externally, integrate with an ingress provider:

```yaml
# charmcraft.yaml
requires:
  ingress:
    interface: ingress
    limit: 1
```

```bash
juju deploy nginx-ingress-integrator --trust
juju integrate my-app:ingress nginx-ingress-integrator:ingress
```

Or use Traefik:

```bash
juju deploy traefik-k8s --trust
juju integrate my-app:ingress traefik-k8s:ingress
```

## Observability

The `charmcraft_init` tool automatically adds the `tracing` relation to `charmcraft.yaml` for all profiles (including PaaS framework profiles). Once COS is deployed, wire up tracing:

```bash
juju integrate my-app:tracing cos.tempo:tracing
```

For standard (non-PaaS) charms, `charmcraft_init` also injects `ops-tracing` into `requirements.txt` and `src/charm.py` — no manual setup needed. For full observability (metrics, logs, dashboards), load the `observability` skill.

## Config Options and Environment Variables

12-factor apps are configured through environment variables. The paas-charm base auto-converts charm config options to environment variables with a framework-specific prefix.

| Framework | Prefix |
|-----------|--------|
| Flask | `FLASK_` |
| Django | `DJANGO_` |
| FastAPI | `FASTAPI_` |
| Go | `APP_` |
| Express | `APP_` |
| Spring Boot | `SPRING_` |

Example — adding a config option:

```yaml
# charmcraft.yaml
config:
  options:
    log-level:
      type: string
      default: "info"
      description: Application log level
```

This becomes the environment variable `FLASK_LOG_LEVEL` (for a Flask app).

## Version Bumps

When updating the application:

1. Bump `version` in `rockcraft.yaml`
2. Run `rockcraft pack` → new `.rock`
3. Push new image with an updated tag (e.g. `0.2`)
4. Run `charmcraft pack` if charm metadata changed
5. `juju refresh my-app --path=./my-app.charm --resource oci-image=localhost:32000/my-app:0.2`

## Common Pitfalls

1. **Forgetting `ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true`** — Go, Express, and FastAPI profiles fail without it.

2. **Missing `resources` section in `charmcraft.yaml`** — the charm cannot pull the OCI image without a declared `oci-image` resource.

3. **Not pushing the rock before deploying** — `juju deploy` pulls the image from the registry; if it is not there, the unit will enter `error` state.

4. **Registry TLS errors** — MicroK8s's built-in registry at `localhost:32000` does not use TLS. Always pass `--dest-tls-verify=false` to skopeo.

5. **Stale images** — after a `rockcraft pack` + push, the K8s node may cache the old image. Use a unique tag (not just `latest`) or delete the pod to force a re-pull.

6. **Wrong profile** — using `kubernetes` profile instead of a framework profile gives you a bare ops charm without the paas-charm base. Always match the profile to the detected framework.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `rockcraft init` fails with "unknown extension" | Experimental flag not set | Set `ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true` |
| Unit stuck in `waiting` | Image not in registry | Push the rock with `skopeo_registry_push` |
| Unit in `error` | Workload crash | Check `juju debug-log` for container errors |
| `blocked: missing relation` | Database or ingress not related | Run `juju_relate` to add the integration |
| Config change has no effect | Wrong env var prefix | Check the framework prefix table above |
