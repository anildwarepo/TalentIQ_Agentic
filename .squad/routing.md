# Work Routing

How to decide who handles what.

## Routing Table

| Work Type | Route To | Examples |
|-----------|----------|----------|
| Architecture & scope | Ripley | System design, API contracts, tech decisions, code review |
| Frontend / UI | Dallas | React components, Vite config, styling, user interactions |
| Backend / APIs | Kane | Python services, Agent Framework, MCP servers, API endpoints |
| Data / Graph DB | Parker | Cypher queries, vector search, full-text search, data models, graph schema |
| Data Generation & Loading | Brett | Generate synthetic talent data, PostgreSQL/AGE loading, DiskANN vectors, FTS indexes, connectivity tests, parallel idempotent loading |
| Testing / QA | Lambert | Write tests, edge cases, verify fixes, quality gates |
| Requirements / Stories | Ash | User stories, epics, specs, requirements decomposition, backlog |
| Code review | Ripley | Review PRs, check quality, suggest improvements |
| Session logging | Scribe | Automatic — never needs routing |

## Issue Routing

| Label | Action | Who |
|-------|--------|-----|
| `squad` | Triage: analyze issue, assign `squad:{member}` label | Ripley |
| `squad:{name}` | Pick up issue and complete the work | Named member |

### How Issue Assignment Works

1. When a GitHub issue gets the `squad` label, **Ripley** triages it — analyzing content, assigning the right `squad:{member}` label, and commenting with triage notes.
2. When a `squad:{member}` label is applied, that member picks up the issue in their next session.
3. Members can reassign by removing their label and adding another member's label.
4. The `squad` label is the "inbox" — untriaged issues waiting for Ripley's review.

## Rules

1. **Eager by default** — spawn all agents who could usefully start work, including anticipatory downstream work.
2. **Scribe always runs** after substantial work, always as `mode: "background"`. Never blocks.
3. **Quick facts → coordinator answers directly.** Don't spawn an agent for "what port does the server run on?"
4. **When two agents could handle it**, pick the one whose domain is the primary concern.
5. **"Team, ..." → fan-out.** Spawn all relevant agents in parallel as `mode: "background"`.
6. **Anticipate downstream work.** If a feature is being built, spawn the tester to write test cases from requirements simultaneously.
7. **Issue-labeled work** — when a `squad:{member}` label is applied to an issue, route to that member. Ripley handles all `squad` (base label) triage.
