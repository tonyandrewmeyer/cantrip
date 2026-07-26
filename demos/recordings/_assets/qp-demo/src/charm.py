"""A tiny example charm packed by quickpack."""

import ops


class QpDemoCharm(ops.CharmBase):
    """A minimal charm used by the quickpack demo recording."""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.framework.observe(self.on.install, self._on_install)

    def _on_install(self, _event: ops.InstallEvent) -> None:
        self.unit.status = ops.ActiveStatus("ready")


if __name__ == "__main__":
    ops.main(QpDemoCharm)
