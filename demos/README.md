# Cantrip demos

Executable walkthroughs of Cantrip's main features, one per file. Each
document was generated with [showboat](https://pypi.org/project/showboat/)
and can be re-verified with:

```bash
uvx showboat verify demos/<file>.md
```

| File | Focus |
|------|-------|
| [01-overview.md](01-overview.md) | The top-level `cantrip` CLI and its sibling tools |
| [02-charmlint.md](02-charmlint.md) | The standalone `charmlint` linter — categories, filtering, JSON output |
| [03-quickpack.md](03-quickpack.md) | The `quickpack` fast charm packer |
| [04-skills.md](04-skills.md) | Load-on-demand charm-building skills |
| [05-transcript-export.md](05-transcript-export.md) | Exporting session transcripts to HTML, Markdown, or JSONL |
| [06-agent-architecture.md](06-agent-architecture.md) | The two-loop agent, work queue, subagents, and tool catalogue |
