"""Background executor package — picks ready tasks and runs subagents.

The executor was split into per-cohort modules in Phase 85.5 to keep
``core.py`` focused on the orchestrator itself.  Public symbols stay
importable from ``cantrip.agent.executor`` directly so external call
sites do not move.
"""

from cantrip.agent.executor.core import _DEFAULT_TASK_TIMEOUT as _DEFAULT_TASK_TIMEOUT
from cantrip.agent.executor.core import _ERROR_COOLDOWN as _ERROR_COOLDOWN
from cantrip.agent.executor.core import _MAX_CONSECUTIVE_ERRORS as _MAX_CONSECUTIVE_ERRORS
from cantrip.agent.executor.core import _MAX_NOOP_COUNT as _MAX_NOOP_COUNT
from cantrip.agent.executor.core import _POLL_INTERVAL as _POLL_INTERVAL
from cantrip.agent.executor.core import _TASK_TIMEOUTS as _TASK_TIMEOUTS
from cantrip.agent.executor.core import DEFAULT_MAX_CONCURRENCY as DEFAULT_MAX_CONCURRENCY
from cantrip.agent.executor.core import BackgroundExecutor as BackgroundExecutor
from cantrip.agent.executor.core import BudgetExceededCallback as BudgetExceededCallback
from cantrip.agent.executor.core import RateLimitedCallback as RateLimitedCallback
from cantrip.agent.executor.core import TaskEventCallback as TaskEventCallback
from cantrip.agent.executor.core import _candidate_id_for as _candidate_id_for
from cantrip.agent.executor.git_service import _DefaultGitService as _DefaultGitService
from cantrip.agent.executor.policies import (
    _DefaultEnvironmentChecker as _DefaultEnvironmentChecker,
)
from cantrip.agent.executor.policies import _DefaultFollowupPlanner as _DefaultFollowupPlanner
from cantrip.agent.executor.store_adapter import _SessionStoreAdapter as _SessionStoreAdapter
