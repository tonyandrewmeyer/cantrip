"""Juju operation tools via Jubilant.

This package splits the former monolithic ``juju.py`` into sub-domain
modules.  Every public tool class is re-exported here so existing
``from cantrip.agent.tools.juju import JujuStatusTool`` imports keep
working unchanged.

Shared helpers and patchable module references live in
:mod:`cantrip.agent.tools.juju._common`; submodules reference them via
the ``_common`` module object so ``mock.patch`` against
``cantrip.agent.tools.juju._common.<name>`` reaches all call sites.
"""

from cantrip.agent.tools.juju._common import (
    _agent_charm_dir,
    _is_k8s_model,
    _juju_available,
)
from cantrip.agent.tools.juju.charm_sync import CharmSyncTool
from cantrip.agent.tools.juju.cli_passthrough import JujuCliTool, JujuTrustTool
from cantrip.agent.tools.juju.lifecycle import (
    BundleDeployTool,
    JujuAddModelTool,
    JujuDeployTool,
    JujuDestroyModelTool,
    JujuRefreshTool,
    JujuRemoveApplicationTool,
)
from cantrip.agent.tools.juju.relations import (
    JujuConsumeTool,
    JujuListOffersTool,
    JujuOfferTool,
    JujuReadRelationDataTool,
    JujuRelateTool,
)
from cantrip.agent.tools.juju.runtime import (
    JujuConfigTool,
    JujuDispatchTool,
    JujuGetAppConfigTool,
    JujuRunActionTool,
    JujuShowUnitTool,
    JujuSSHTool,
    JujuStatusTool,
    JujuWaitTool,
    _validate_config_against_charm,
)
from cantrip.agent.tools.juju.secrets import JujuListSecretsTool, JujuShowSecretTool

__all__ = [
    "BundleDeployTool",
    "CharmSyncTool",
    "JujuAddModelTool",
    "JujuCliTool",
    "JujuConfigTool",
    "JujuConsumeTool",
    "JujuDeployTool",
    "JujuDestroyModelTool",
    "JujuDispatchTool",
    "JujuGetAppConfigTool",
    "JujuListOffersTool",
    "JujuListSecretsTool",
    "JujuOfferTool",
    "JujuReadRelationDataTool",
    "JujuRefreshTool",
    "JujuRelateTool",
    "JujuRemoveApplicationTool",
    "JujuRunActionTool",
    "JujuSSHTool",
    "JujuShowSecretTool",
    "JujuShowUnitTool",
    "JujuStatusTool",
    "JujuTrustTool",
    "JujuWaitTool",
    "_agent_charm_dir",
    "_is_k8s_model",
    "_juju_available",
    "_validate_config_against_charm",
]
