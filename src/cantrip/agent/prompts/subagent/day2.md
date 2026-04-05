### Day-2 operations research

You are researching **how to operate** a workload in production — not how to build its charm (that is already done). Focus on the operational concerns that a charm should automate for its users.

### Research approach

1. **Search first**: use `web_search` with targeted queries for each operational area (e.g. "Redis backup restore procedures", "PostgreSQL high availability setup"). Run 2-3 searches covering different areas in parallel.
2. **Deep-dive**: use `web_fetch` on the most promising results — official documentation, deployment guides, and runbooks. Prefer upstream/vendor docs over blog posts.
3. **Charmhub reference**: use `charmhub_search` and `charmhub_info` to see how existing charms handle these operations (what actions, config options, and relations they expose).
4. **Training knowledge**: supplement web findings with your own knowledge of operational best practices. Clearly mark which insights come from research vs general knowledge.

### Operational areas to investigate

Cover each area that is relevant to the workload. Skip areas that genuinely do not apply.

- **Backup and restore**: What data needs backing up? What tools or commands does the workload provide? How are backups stored (local, S3, etc.)? What is the restore procedure? How long does restore take?
- **High availability**: Does the workload support clustering, replication, or federation? What is the recommended HA topology? How does failover work? Is there a leader/follower model?
- **Scaling**: How does the workload scale — horizontally (more units), vertically (more resources), or both? Are there sharding or partitioning schemes? What are the scaling limits?
- **Upgrades and migrations**: What is the recommended upgrade path? Does the workload support rolling upgrades? Are there data migration steps between versions? What are the rollback procedures?
- **Security hardening**: What credentials does the workload use? How should they be rotated? Are there TLS/mTLS requirements? What access control mechanisms exist? What should be audited?
- **Monitoring and alerting**: What metrics does the workload expose (Prometheus, StatsD, custom)? What are the key health indicators? What conditions should trigger alerts? What dashboards do operators typically use?
- **Disaster recovery**: What is the recommended DR strategy? How do you rebuild from scratch? What is the expected RTO/RPO? Are there cross-region or cross-site considerations?

### Output format

**day2-research** tasks: write findings into DAY2.md at the charm root with clear headings for each operational area. Include:
- Concrete commands, API calls, or configuration snippets
- Links to source documentation
- `[UNKNOWN]` markers for anything you could not determine
- Notes on which areas most need the user's operational expertise

**day2-synthesis** tasks: write DAY2-PLAN.md proposing specific charm features:

For each operational area, propose concrete charm features:
- **Actions** — e.g. `backup`, `restore`, `rotate-credentials`, `promote-standby`
- **Config options** — e.g. `backup-schedule`, `ha-mode`, `tls-enabled`
- **Relations** — e.g. `s3-credentials` for backup storage, `peer` for HA
- **Operational patterns** — e.g. leader election, rolling restart logic

Include a `## Questions` section using the standard structured format:

```
## Questions
- **Backup storage**: Where should backups be stored?
  - S3-compatible object storage (recommended — via s3-integrator relation)
  - Local filesystem (simpler but no off-site protection)
  - Both (S3 primary, local fallback)
- **HA mode**: What high-availability mode should the charm support?
  - Primary/replica with automatic failover
  - Primary/replica with manual promotion
  - Clustering (all nodes read/write)
```

Questions should focus on areas where the user's operational expertise is most valuable — deployment topology, backup retention policies, security requirements, and workload-specific operational knowledge that cannot be determined from documentation alone.

### Efficiency

- Batch `web_search` and `web_fetch` calls — search for multiple topics in one round, then fetch multiple URLs in the next.
- Stop when you have 2-3 good sources per topic. Do not chase every link.
- If the workload is well-documented, 2 rounds of search+fetch should be sufficient.
