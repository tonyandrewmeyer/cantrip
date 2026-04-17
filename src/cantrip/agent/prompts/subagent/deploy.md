Pack the charm and deploy it. Ensure all relations are established and the application reaches active/idle status. Use `juju_wait` to confirm readiness rather than polling `juju_status` repeatedly.

**Packing**: prefer `quick_pack` — it skips LXD, linting, and analysis and is typically 2–5× faster than `charmcraft pack`.  Requires the `uv` parts plugin and a `uv.lock`.  If `quick_pack` fails (unsupported plugin, `override-build` in parts, missing `uv.lock`), fall back to `charmcraft_pack` with `destructive_mode=true` in dev.  For `.py`-only iterations on a charm that is *already deployed*, `charm_sync` (jhack sync) is even faster because it bypasses Juju's deploy/refresh; only use it when you don't specifically need to exercise install/upgrade hooks.

**Companion charms**: if the approved design lists companion charms (in a `## Companion charms` section), deploy each companion from Charmhub *before* relating them to the primary charm. For each companion, use `juju_deploy` with the charm name from Charmhub, then `juju_relate` using the endpoint and interface specified in the design. Wait for all applications to settle before reporting success.

**Efficiency**: chain pack → deploy → wait in as few rounds as possible. Establish all relations in a single round.
