# Roadmap

Planned work not yet scheduled. Items here are commitments of direction, not design specs; each gets its own planning document before implementation.

## Report export service (MD → HTML / plain text)

**Status:** planned
**Motivation:** ticket reports must eventually be delivered to external platforms via webhook/API. Known target: a SOHO ticketing platform that accepts only HTML and plain text — not Markdown.

**Scope:**

- Internal server-side converter from the canonical report format (GitHub-flavored Markdown, produced by the Engineer agent's `submit_findings.summary`) to:
  - HTML (sanitized, self-contained fragment)
  - plain text (headings/lists preserved as readable text, markup stripped)
- Markdown remains the single source of truth stored in `agent_runs.final_answer`; conversions are derived on demand, never persisted as the primary copy.
- Candidate libraries: `markdown-it-py` or `mistune` for MD→HTML; MD→text via render + tag strip.

**Integration points:**

- `GET /tickets/{ticket_id}/report?format=md|html|text` (default `md`, current behavior unchanged).
- Outbound notification egress (`src/notifications/`, implemented since): `run.completed` already delivers the findings as Markdown; format selection would apply here when the destination platform accepts only HTML or plain text.

**Out of scope for now:** PDF export, templating/branding of exported reports.
