# Cantrip Agent Architecture

## Overview

Hybrid architecture: main agent handles conversation and coordination, background agents handle async tasks.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Main Agent                               │
│                                                                 │
│  • Conversation with user                                       │
│  • Charm code writing                                           │
│  • Decision making                                              │
│  • Tool orchestration                                           │
│  • Background agent spawning                                    │
│                                                                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┬───────────────┐
         │               │               │               │
         ▼               ▼               ▼               ▼
   ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
   │   Test    │  │  Research │  │   Trace   │  │  Charmhub │
   │   Agent   │  │   Agent   │  │   Agent   │  │   Agent   │
   │           │  │           │  │           │  │           │
   │ • Scenario│  │ • Web     │  │ • Tempo   │  │ • Search  │
   │ • Jubilant│  │ • Docs    │  │ • Loki    │  │ • Libs    │
   └───────────┘  └───────────┘  └───────────┘  └───────────┘
```

## Main Agent

### System Prompt Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                     SYSTEM PROMPT                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Identity & Purpose                                          │
│     "You are Cantrip, an AI agent that builds Juju charms..."   │
│                                                                 │
│  2. Core Principles                                             │
│     - Get to active/running fast                                │
│     - User provides operational knowledge                       │
│     - Agent handles implementation                              │
│     - Show off the Canonical ecosystem                          │
│                                                                 │
│  3. Charm Development Guidance                                  │
│     (from charming-with-claude + additional docs)               │
│     - Modern patterns (Scenario, Jubilant)                      │
│     - Avoid deprecated (Harness, pytest-operator)               │
│     - Library preferences (PyPI > Charmhub)                     │
│                                                                 │
│  4. Tools Available                                             │
│     (see Tools section below)                                   │
│                                                                 │
│  5. Current Context                                             │
│     - Active charm project                                      │
│     - Environment state                                         │
│     - Recent decisions                                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Identity & Purpose

```markdown
You are Cantrip, an AI agent specialised in building Juju charms.

Your goal is to help users create production-quality charms through natural
conversation. You handle the implementation; the user provides operational
knowledge about how their application should behave.

You showcase the Canonical ecosystem: Juju, Charmcraft, Rockcraft, Ops,
Jubilant, Concierge, and COS. These tools are the durable foundation;
you make them accessible.

Key principles:
1. Get to active/running status fast (2 minutes for simple charms)
2. Iterate through conversation - don't try to be perfect first time
3. Use observability (traces, logs) to debug issues
4. Default to fast dev cycle (juju ssh), validate with full pack/refresh
5. Integrate with the ecosystem - observability, databases, ingress
```

### Charm Development Guidance

This section incorporates content from charming-with-claude and additional docs:

```markdown
## Charm Development Standards

### Testing
- Unit tests: Use Scenario (ops.testing Context, State)
- Integration tests: Use Jubilant
- NEVER use: Harness (deprecated), pytest-operator, python-libjuju

### Libraries
- Prefer PyPI versions where available: [list]
- Use charmcraft.yaml + fetch-libs for Charmhub libraries
- Always include: ops-tracing for observability

### Patterns
- 12-factor apps: Use paas-charm base
- Custom apps: Full ops framework charm
- Infrastructure: Research operational patterns first

### Code Style
- UK English for all text
- Type hints throughout
- Pydantic for config models where appropriate

### Common Integrations
- Observability: Always include COS integration
- Database: Support all databases the workload supports
- Ingress: Traefik for K8s charms
```

### Current Context

Injected at runtime based on session state:

```markdown
## Current Project

Charm: flask-app-charm
Path: /home/user/flask-app-charm
Type: K8s (12-factor)
Framework: Flask 2.3

## Environment

Dev Model: dev (Canonical K8s)
- flask-app: active (1 unit)
- postgresql: active (1 unit)

COS Model: cos (Canonical K8s)
- All components healthy

## Recent Decisions

- Using PostgreSQL (user choice over MySQL)
- Added custom /health endpoint
- Tracing enabled
```

## Tools

### Juju Operations (via Jubilant)

```python
class JujuTools:
    """Tools for Juju operations via Jubilant."""

    def get_status(self, model: str = None) -> JujuStatus:
        """Get current juju status as structured data."""

    def deploy(self, charm: str, app_name: str, config: dict = None) -> None:
        """Deploy a charm."""

    def refresh(self, app_name: str, path: str = None) -> None:
        """Refresh a deployed charm."""

    def relate(self, app1: str, app2: str, relation: str = None) -> None:
        """Create a relation between apps."""

    def run_action(self, unit: str, action: str, params: dict = None) -> ActionResult:
        """Run an action on a unit."""

    def ssh(self, unit: str, command: str) -> str:
        """Execute command on a unit via SSH."""

    def ssh_write(self, unit: str, path: str, content: str) -> None:
        """Write content to a file on a unit (fast dev cycle)."""
```

### Charm Operations

```python
class CharmTools:
    """Tools for charm creation and modification."""

    def init(self, name: str, profile: str = "machine") -> Path:
        """Run charmcraft init to scaffold a charm."""

    def pack(self, path: str = ".") -> Path:
        """Pack a charm, return path to .charm file."""

    def fetch_libs(self, path: str = ".") -> None:
        """Fetch charm libraries defined in charmcraft.yaml."""

    def add_lib(self, charm: str, lib: str) -> None:
        """Add a library to charmcraft.yaml."""
```

### File Operations

```python
class FileTools:
    """Tools for reading and writing charm files."""

    def read(self, path: str) -> str:
        """Read a file."""

    def write(self, path: str, content: str) -> None:
        """Write a file."""

    def edit(self, path: str, old: str, new: str) -> None:
        """Replace text in a file."""

    def list_dir(self, path: str) -> list[str]:
        """List directory contents."""
```

### Environment (via Concierge)

```python
class EnvironmentTools:
    """Tools for environment management via Concierge."""

    def setup(self, preset: str) -> None:
        """Set up environment: 'lxd' or 'k8s'."""

    def status(self) -> EnvironmentStatus:
        """Get current environment status."""

    def teardown(self, model: str = None) -> None:
        """Tear down a model or entire environment."""
```

### Observability

```python
class ObservabilityTools:
    """Tools for querying COS."""

    def query_traces(self, service: str, since: str = "1h") -> list[Trace]:
        """Query Tempo for traces."""

    def query_logs(self, app: str, since: str = "1h", filter: str = None) -> list[LogEntry]:
        """Query Loki for logs."""

    def get_metrics(self, app: str, metric: str) -> MetricData:
        """Query Prometheus for metrics."""

    def grafana_url(self, dashboard: str = None) -> str:
        """Get Grafana URL for a dashboard."""
```

### Charmhub

```python
class CharmhubTools:
    """Tools for Charmhub interaction."""

    def search(self, query: str, type: str = None) -> list[CharmInfo]:
        """Search Charmhub for charms."""

    def info(self, charm: str) -> CharmDetails:
        """Get detailed info about a charm."""

    def get_libs(self, charm: str) -> list[LibraryInfo]:
        """List libraries provided by a charm."""
```

### Background Agents

```python
class AgentTools:
    """Tools for spawning background agents."""

    def run_tests(self, test_type: str = "all") -> TaskHandle:
        """Spawn background agent to run tests."""

    def research(self, query: str) -> TaskHandle:
        """Spawn background agent to research a topic."""

    def analyse_traces(self, issue: str) -> TaskHandle:
        """Spawn background agent to analyse traces for an issue."""

    def task_status(self, handle: TaskHandle) -> TaskStatus:
        """Check status of a background task."""

    def task_result(self, handle: TaskHandle) -> TaskResult:
        """Get result of a completed background task."""
```

## Background Agents

Each background agent has a focused system prompt and limited tools.

### Test Agent

```markdown
You are a test runner agent for Cantrip.

Your job is to run charm tests and report results clearly.

Tools available:
- Run Scenario unit tests
- Run Jubilant integration tests
- Report results

Do not modify code. Report what passed, what failed, and why.
```

### Research Agent

```markdown
You are a research agent for Cantrip.

Your job is to find information about software, patterns, and best practices.

Tools available:
- Web search
- Documentation fetch
- Charmhub search

Return structured findings. Be thorough but concise.
```

### Trace Agent

```markdown
You are a trace analysis agent for Cantrip.

Your job is to analyse traces and logs to identify issues.

Tools available:
- Tempo trace queries
- Loki log queries
- Prometheus metric queries

Identify the root cause. Explain what's happening and suggest fixes.
```

### Charmhub Agent

```markdown
You are a Charmhub agent for Cantrip.

Your job is to search Charmhub and find relevant charms and libraries.

Tools available:
- Charmhub search
- Charm info
- Library listing

Find charms that could integrate with the user's charm.
Check compatibility and recommend integrations.
```

## Conversation Flow

### Initial Charm Request

```
User: build a charm for my flask app

Agent thinking:
1. This is a 12-factor app (Flask)
2. Need to determine: K8s or machine?
3. Need to find the code (ask or detect)
4. Use paas-charm base
5. Goal: active/running in 2 minutes

Agent response:
"I'll create a 12-factor charm for your Flask application.

Is this a K8s charm or machine charm? (I'd suggest K8s since Flask apps
typically work well containerised)

And where's the code? Current directory, or a specific path?"
```

### Adding Integrations

```
User: add postgresql integration

Agent thinking:
1. User wants database integration
2. Check if workload supports PostgreSQL
3. Add relation to charmcraft.yaml
4. Add integration code to charm.py
5. Deploy postgresql charm and relate

Agent actions:
1. Edit charmcraft.yaml to add postgresql relation
2. Edit src/charm.py to handle relation events
3. Deploy postgresql if not present
4. juju relate flask-app postgresql
5. Verify connection via traces
```

### Debugging

```
User: the app isn't starting

Agent thinking:
1. Something's wrong - need to investigate
2. Check traces first (observability-driven)
3. Check logs if traces don't show issue
4. Identify root cause
5. Fix and verify

Agent actions:
1. Query Tempo for recent traces
2. "I can see the startup is failing at database connection"
3. Query Loki for detailed logs
4. "The DATABASE_URL environment variable isn't set"
5. Fix charm.py to set env var from relation data
6. Fast path: juju ssh to update code
7. Trigger hook re-run
8. Verify via traces
```

## Context Management

### Session State

```python
@dataclass
class SessionState:
    """Persisted in .cantrip/session.json"""

    charm_name: str
    charm_path: Path
    charm_type: Literal["machine", "k8s"]
    framework: str | None  # Flask, Django, etc.

    dev_model: str
    cos_model: str

    decisions: list[Decision]  # Key decisions made

    conversation_summary: str  # Summarised older turns
    recent_turns: list[Turn]   # Recent turns verbatim
```

### Context Window Strategy

1. **Always include:**
   - System prompt (identity, principles, guidance)
   - Current project state
   - Recent decisions
   - Last 5-10 conversation turns

2. **Summarise:**
   - Older conversation turns
   - Completed tasks
   - Resolved issues

3. **On demand:**
   - File contents (read when needed)
   - Full trace data (query when debugging)
   - Test results (fetch when relevant)

### Decision Tracking

```yaml
# .cantrip/decisions.yaml
decisions:
  - id: 1
    timestamp: "2024-01-15T10:30:00Z"
    type: database
    choice: postgresql
    reason: "User preference over MySQL"

  - id: 2
    timestamp: "2024-01-15T10:35:00Z"
    type: integration
    choice: traefik-ingress
    reason: "Standard ingress for K8s charms"
```

## Error Handling

### User-Facing Errors

```python
class CantripError(Exception):
    """Base error with user-friendly message."""

    def __init__(self, message: str, suggestion: str = None):
        self.message = message
        self.suggestion = suggestion

class CharmPackError(CantripError):
    """Charm failed to pack."""

class DeployError(CantripError):
    """Deployment failed."""

class TestError(CantripError):
    """Tests failed."""
```

### Recovery Strategies

1. **Pack failure:** Show error, suggest fixes, offer to attempt auto-fix
2. **Deploy failure:** Show juju status, check for common issues
3. **Test failure:** Show which tests failed, offer to investigate
4. **Connection failure:** Check environment, offer to reset

## LLM Provider Interface

```python
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] = None,
        temperature: float = 0.7,
    ) -> Response:
        """Generate a completion."""

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[Chunk]:
        """Stream a completion."""


class GeminiProvider(LLMProvider):
    """Google Gemini implementation."""

    def __init__(self, api_key: str, model: str = "gemini-pro"):
        ...


class ClaudeProvider(LLMProvider):
    """Anthropic Claude implementation."""

    def __init__(self, api_key: str, model: str = "claude-3-opus"):
        ...
```
