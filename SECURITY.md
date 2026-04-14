# Security Policy

## Supported Versions

Cantrip is pre-1.0 and under active development. Security fixes are applied to the latest version on the `main` branch.

| Version   | Supported          |
| --------- | ------------------ |
| main HEAD | Yes                |
| Older     | No                 |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them by emailing the maintainers directly. You can find contact information in `pyproject.toml` or on the repository's contributor profiles.

When reporting, please include:

- A description of the vulnerability
- Steps to reproduce the issue
- The potential impact
- Any suggested fix, if you have one

We aim to acknowledge reports within 48 hours and will work with you to understand and address the issue before any public disclosure.

## Security Considerations

Cantrip is an AI agent that executes code and interacts with infrastructure. Users should be aware of the following:

### LLM-Generated Code Execution

Cantrip generates and executes charm code, shell commands, and deployment configurations based on LLM output. While the agent includes guardrails:

- **Review generated code** before deploying to production environments
- **Use dedicated development models** (Juju models) rather than production infrastructure
- **Inspect the `.cantrip` session file** to audit what the agent did

### API Keys

- Cantrip reads API keys from environment variables (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`)
- Keys are never written to disk or included in generated charm code
- Use scoped API keys with minimal permissions where possible

### Tool Execution

- File tools operate within the charm project directory; path traversal is prevented by `PathAwareTool` resolution
- The `run_command` tool executes shell commands in a sandboxed working directory with timeout and output limits
- Juju tools interact with your active Juju controller and models — ensure you are connected to the intended environment
- Web tools (`web_fetch`, `web_search`) make outbound HTTP requests to external sites

### Network Access

- LLM provider calls are made to external APIs (Google, Anthropic) unless using a local inference snap
- Web research tools fetch content from the public internet
- The Web UI (`--web`) binds to `localhost` by default; do not expose it to untrusted networks without additional authentication

### Dependencies

- Dependencies are managed via `uv` and pinned in `uv.lock`
- We monitor for known vulnerabilities in dependencies and update promptly
