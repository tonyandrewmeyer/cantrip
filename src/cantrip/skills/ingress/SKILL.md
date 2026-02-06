---
name: ingress
description: Configuring HTTP ingress with Traefik for Kubernetes charms
---

# Ingress with Traefik

Kubernetes charms that serve HTTP traffic need ingress to be reachable from outside the cluster. The standard approach in the Juju ecosystem is **Traefik** via the `ingress` relation.

## Key Concepts

- **Ingress** — routes external HTTP/HTTPS traffic to a Kubernetes service
- **Traefik** — the ingress controller used in the Juju ecosystem (`traefik-k8s`)
- **`ingress` relation** — the standard interface for requesting ingress from Traefik
- **Per-app vs per-unit ingress** — most charms use per-app (single URL); some need per-unit (e.g., distributed databases)

## Step 1: Add the Ingress Relation

In `charmcraft.yaml`:

```yaml
requires:
  ingress:
    interface: ingress
    limit: 1
```

## Step 2: Use the Ingress Library

Install or fetch the `traefik_route` / `ingress` library:

```bash
charmcraft fetch-lib charms.traefik_k8s.v2.ingress
```

Integrate in the charm:

```python
import ops

from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._ingress = IngressPerAppRequirer(
            self,
            relation_name="ingress",
            port=8080,
        )
        self.framework.observe(
            self._ingress.on.ready,
            self._on_ingress_ready,
        )
        self.framework.observe(
            self._ingress.on.revoked,
            self._on_ingress_revoked,
        )

    def _on_ingress_ready(self, event):
        url = self._ingress.url
        # Store or use the external URL.
        self.unit.status = ops.ActiveStatus(f"serving at {url}")

    def _on_ingress_revoked(self, event):
        self.unit.status = ops.ActiveStatus("running (no ingress)")
```

## Step 3: Deploy Traefik and Relate

```bash
juju deploy traefik-k8s --trust --channel latest/stable
juju integrate my-charm:ingress traefik-k8s:ingress
```

## Step 4: Configure TLS (Optional)

For HTTPS, configure Traefik with a TLS certificate:

```bash
# Use the self-signed certificates operator for development.
juju deploy self-signed-certificates
juju integrate traefik-k8s:certificates self-signed-certificates:certificates
```

For production, use a proper certificate provider (e.g., `tls-certificates-operator` with Let's Encrypt or a CA).

## Step 5: Per-Unit Ingress (Advanced)

Some applications need individual URLs per unit (e.g., database nodes that clients connect to directly):

```python
from charms.traefik_k8s.v2.ingress import IngressPerUnitRequirer


class MyDBCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._ingress = IngressPerUnitRequirer(
            self,
            relation_name="ingress",
            port=5432,
        )
```

This gives each unit its own external URL (e.g., `mydb-0.example.com`, `mydb-1.example.com`).

## Step 6: Verify Ingress

After relating:

```bash
# Check the Traefik status.
juju status traefik-k8s

# Get the external URL.
juju run traefik-k8s/0 show-proxied-endpoints
```

Test connectivity:

```bash
curl http://<traefik-ip>/<model>-<app>
```

## Configuration Options

The ingress library supports several configuration options:

- **`port`** — the container port to route traffic to (required)
- **`scheme`** — `http` or `https` (default: `http`)
- **`strip_prefix`** — whether to strip the URL prefix before forwarding (default: `False`)

## Best Practices

1. **Use `IngressPerAppRequirer` by default.** Most web applications need a single URL. Only use per-unit ingress for stateful workloads where clients need to address specific replicas.

2. **Always declare the port.** The ingress library needs to know which port the workload listens on.

3. **Handle ingress revocation.** The charm should continue to function without ingress — it just will not be externally reachable.

4. **Use `--trust` when deploying Traefik.** It needs cluster-wide permissions to manage ingress resources.

5. **12-factor PaaS charms get ingress automatically** when using the paas-charm base with Traefik. No manual library integration is needed.

## Common Pitfalls

- **Forgetting `--trust`** on the Traefik deployment — it will fail to create ingress resources.
- **Wrong port number** — ensure the port matches what the workload actually listens on inside the container.
- **Assuming HTTPS by default** — Traefik serves HTTP unless explicitly configured with certificates.
- **Not handling the `revoked` event** — the charm should update its status when ingress is removed.
