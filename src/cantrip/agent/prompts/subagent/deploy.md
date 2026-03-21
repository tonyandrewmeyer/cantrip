Pack the charm and deploy it. Ensure all relations are established and the application reaches active/idle status. Use `juju_wait` to confirm readiness rather than polling `juju_status` repeatedly.

**Companion charms**: if the approved design lists companion charms (in a `## Companion charms` section), deploy each companion from Charmhub *before* relating them to the primary charm. For each companion, use `juju_deploy` with the charm name from Charmhub, then `juju_relate` using the endpoint and interface specified in the design. Wait for all applications to settle before reporting success.

**Efficiency**: chain pack → deploy → wait in as few rounds as possible. Establish all relations in a single round.
