# Project Context

- **Owner:** Anil
- **Project:** TalentIQ — Talent Matching/Searching platform. Find people with skills, generate resumes based on RFPs, show metrics visuals.
- **Stack:** React Vite (frontend), Python (backend), Agent Framework with agentic orchestration, MCP servers, Graph database (Cypher, vector search, full-text search)
- **Features:** Chat interface, FAQs, file upload, resume generation from RFPs, metrics visualization
- **Requirements source:** `talentiq_requirements/` folder contains CSV files (AI Talent Matching, feature-to-story mapping, user stories) and markdown requirement docs (REQ-01, REQ-02)
- **Created:** 2026-05-08

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-05-08: Full requirements decomposition (fresh start)

**What was done:**
- Complete fresh decomposition from `talentiq_requirements/user_stories_v9.csv` (52 user stories, 17 epics) and `talentiq_requirements/features.csv` (48 AI-matching features)
- Created 72 files total:
  - `docs/specs/product-spec.md` — high-level product specification
  - `docs/backlog.md` — prioritized backlog by sprint (164 story points across 7 sprints + backlog)
  - `docs/traceability.md` — cross-reference matrix (features → stories → epics → BRs)
  - `docs/epics/EPIC-01.md` through `docs/epics/EPIC-17.md` — 17 epic files
  - `docs/user-stories/US-001.md` through `docs/user-stories/US-052.md` — 52 user story files

**Key findings:**
- 18 of 48 features.csv entries are covered by existing user stories (some partially)
- 30 features are GAPS with no corresponding user stories — highest priority gaps are AI scoring dimensions, Match Readiness tiers, Shortlist management, Career Navigator, and Phased AI Adoption
- Recommended 3 new epics for gap features: EPIC-18 (Match Readiness), EPIC-19 (Career Navigator), EPIC-20 (Phased AI Adoption)
- Sprint distribution: Sprint 1 (17pts), Sprint 2 (10pts), Sprint 3 (26pts), Sprint 4 (32pts), Sprint 5 (28pts), Sprint 6 (2pts), Sprint 7 (16pts), Backlog (33pts)
- EPIC-04 (Candidate Search) has the most gap features (18) — this is the AI scoring core
- EPIC-17 (CPQ) is P1 priority but unscheduled — pending CPQ integration timeline
- US-034/035/036 overlap with US-017/018/019 — bid-specific variants reusing the same CV generation engine

**File structure patterns:**
- Epics: `docs/epics/EPIC-{NN}.md`
- User stories: `docs/user-stories/US-{NNN}.md`
- Each user story has: description, acceptance criteria (checkboxes), tags, feature coverage, dependencies, notes
- Each epic has: summary, story table, dependencies, acceptance criteria
- Business requirements traced: BR-01 through BR-15, BR-EQF, BR-CPQ


## Cross-agent note — 2026-05-22T22:30:00Z (Scribe)
- **Model directive (Anil, captured 2026-05-22T18:30:00Z):** all squad spawns — including Scribe and Ralph, including any agent normally defaulted to a fast/cheap tier — MUST use `claude-opus-4.6-1m` (Opus 4.7 Extra-high reasoning). `.squad/config.json` `defaultModel` is the source of truth; the "never bump Scribe" rule is overridden. Per `decisions.md` `2026-05-22T18:30:00Z`.
