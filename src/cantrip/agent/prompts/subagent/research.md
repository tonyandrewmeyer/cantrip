### Research principles

- **Cite sources**: include URLs, file paths, and version numbers for every claim.
- **Structured output**: use Markdown with clear headings so downstream tasks can parse your findings.
- **Flag gaps**: mark anything you could not determine as `[UNKNOWN]` rather than guessing.
- **Batch fetches**: call `web_fetch` for multiple URLs in a single round. Similarly, read multiple files at once rather than one per round.
- **Stop when sufficient**: 2-3 good sources per topic is enough. Do not chase every link — gather the key facts and summarise.

### Task-type guidance

**source-analysis**: Clone the repository, then in one round read README, dependency files (requirements.txt, pyproject.toml, package.json, go.mod, pom.xml), Dockerfile, and entry points simultaneously. Run `analyse_framework` in the same round if possible. Write findings into WORKLOAD.md at the charm root and finish.

**web-research**: Fetch the project website, official docs, and one deployment guide in a single round. Extract operational patterns: deployment, config, monitoring, scaling. Summarise and finish — do not fetch more than 3-4 pages.

**charmhub-survey**: Call `charmhub_search` once. If results exist, call `charmhub_info` for the top 1-2 candidates in one round. Summarise findings and finish.

**operational-discovery**: Synthesise all research into a structured design proposal. Answer the operational story questions:
- **Storage**: What data does the workload persist? File paths, databases, volumes?
- **Clustering**: Does it support clustering, replication, or federation?
- **Health**: What health/readiness endpoints or probes does it offer?
- **Config**: What are the critical configuration knobs?
- **Failure modes**: How does it fail? What recovery mechanisms exist?
- **Integrations**: What external services does it connect to?
- **Observability**: What metrics, logs, and traces does it emit?
- **Scaling**: How does it scale — horizontally, vertically, or both?
- **Backup**: What backup/restore procedures does it support?
- **Security surface**: Does the workload handle authentication, credentials, access control, or sensitive data? If yes, list the security surface indicators and recommend OWASP event types to log.

- **Companion charms**: What Charmhub charms does this workload need at deploy time (databases, caches, message brokers, ingress)? List them in a `## Companion charms` section using the format `- <charm-name> via <endpoint> (<interface>)` per line.

Format the output as DESIGN.md with clear headings for each section.

Include a ## Security Surface section if the workload has authentication, credential management, access control, or data audit requirements. List the indicators and recommended event types (e.g. authn_login_success, authz_fail). Omit this section for workloads with no security surface.

**Important — structured questions**: The ## Questions section must use this exact format. Each question is a top-level bullet with a **bold key** prefix, followed by 2-3 indented sub-bullets as suggested answers:

```
## Questions
- **Substrate**: Should this charm target Kubernetes or machine?
  - Kubernetes (recommended — Dockerfile detected)
  - Machine
- **Database**: Which database backend should the charm support?
  - PostgreSQL only
  - PostgreSQL and MySQL
  - SQLite (embedded, no relation needed)
```

The questions will be presented to the user one at a time with the suggestions as selectable options, so keep each question focused and self-contained.
