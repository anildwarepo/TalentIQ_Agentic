# TalentIQ v2 — Traceability Matrix

> **Date:** 2026-05-08  
> **Purpose:** Cross-reference features.csv entries to user stories and epics. Identify coverage gaps.

---

## Feature → User Story Mapping

### Covered Features (18 of 48)

| Feature ID | Feature | Category | Mapped User Stories | Epic | Coverage |
|-----------|---------|----------|-------------------|------|----------|
| M05-01 | AI scoring: skills match (direct keyword matching) | Scoring | US-009 | EPIC-04 | ✅ Full |
| M05-02 | AI scoring: skills match (semantic similarity scoring) | Scoring | US-009, US-015 | EPIC-04 | ✅ Full |
| M05-04 | AI scoring: location match | Scoring | US-009, US-010 | EPIC-04 | ✅ Full |
| M05-06 | AI scoring: job level alignment | Scoring | US-009 | EPIC-04 | ✅ Full |
| M05-10 | GDN vs location-specific matching constraint | Matching Constraints | US-010 | EPIC-04 | ⚠️ Partial — not explicit, covered by general filters |
| M05-11 | Language as hard filter | Matching Constraints | US-009 | EPIC-04 | ✅ Full |
| M05-15 | Match Readiness: Developable → training pathway | Match Readiness | US-014 | EPIC-04 | ⚠️ Partial — training suggestions present but not Match Readiness tier |
| M05-19 | Shortlist: persistent object per RR | Shortlist | US-022 | EPIC-06 | ⚠️ Partial — response packages exist, not named "shortlist" |
| M05-20 | Shortlist: ranked candidate list with AI scores | Shortlist | US-009 | EPIC-04 | ✅ Full — impressiveness score, sortable |
| M05-21 | Shortlist: shareable between RM, PM, hiring manager | Shortlist | US-022 | EPIC-06 | ⚠️ Partial — packages shareable but no explicit sharing model |
| M05-22 | Shortlist: add/remove candidates manually | Shortlist | US-022 | EPIC-06 | ✅ Full |
| M05-29 | Career Navigator: skill gap visibility | Career Navigator | US-014 | EPIC-04 | ⚠️ Partial — manager-facing gaps, not employee-facing |
| M05-32 | Match explainability: score breakdown by dimension | Explainability | US-003, US-009 | EPIC-01, EPIC-04 | ⚠️ Partial — data source shown, score breakdown via hover |
| M05-35 | Feedback loop: capture acceptance reason | Feedback Loop | US-043 | EPIC-13 | ⚠️ Partial — thumbs only, no structured reasons |
| M05-36 | Feedback loop: capture rejection reason | Feedback Loop | US-043 | EPIC-13 | ⚠️ Partial — thumbs only, no structured reasons |
| M05-38 | AI matching configuration: admin-tunable weights | Configuration | US-009 | EPIC-04 | ✅ Full — configurable weights, must sum to 100% |
| M05-43 | Match performance metrics | Analytics | US-052 | EPIC-17 | ⚠️ Partial — talent preview analytics only |
| M05-48 | Matching audit trail | Governance | US-051 | EPIC-17 | ⚠️ Partial — talent preview audit only, not general matching |

### Gap Features (30 of 48) — No Corresponding User Stories

| Feature ID | Feature | Category | Suggested Epic | Priority | Notes |
|-----------|---------|----------|---------------|----------|-------|
| M05-03 | AI scoring: availability (hours/allocation) | Scoring | EPIC-04 | High | Core scoring dimension missing from stories |
| M05-05 | AI scoring: cost optimization (resource cost vs bill rate) | Scoring | EPIC-04 | High | Revenue optimization, needs finance data |
| M05-07 | AI scoring: engagement history (past performance) | Scoring | EPIC-04 | High | Requires project history data source |
| M05-08 | AI scoring: client familiarity (previous work) | Scoring | EPIC-04 | Medium | Requires client-project mapping |
| M05-09 | AI scoring: bench duration (longer bench = higher priority) | Scoring | EPIC-04 | High | Bench management priority |
| M05-12 | Match Readiness: High → auto-recommend to RM | Match Readiness | New EPIC | High | No Match Readiness framework in stories |
| M05-13 | Match Readiness: Medium → RM validation required | Match Readiness | New EPIC | High | Requires approval workflow |
| M05-14 | Match Readiness: Low → manual review required | Match Readiness | New EPIC | Medium | Edge case handling |
| M05-16 | Mandatory internal search before external (audit trail) | Governance | EPIC-10 | High | Compliance requirement |
| M05-17 | Bench-first priority: bench resources weighted higher | Scoring | EPIC-04 | High | Bench utilization optimization |
| M05-18 | Bench aging weighting: longer bench = higher score boost | Scoring | EPIC-04 | Medium | Refinement of M05-09 |
| M05-23 | Shortlist: Career Navigator self-nominations auto-added | Shortlist | New EPIC | Medium | Depends on Career Navigator |
| M05-24 | Shortlist: comparison view (side-by-side) | Shortlist | EPIC-04 | Medium | UX enhancement |
| M05-25 | Shortlist: RM notes per candidate | Shortlist | EPIC-04 | Medium | Collaboration feature |
| M05-26 | Shortlist: status tracking per candidate | Shortlist | EPIC-04 | Medium | Workflow tracking |
| M05-27 | Career Navigator: employee-facing opportunity browser | Career Navigator | New EPIC | Medium | New employee-facing module |
| M05-28 | Career Navigator: self-nomination with justification | Career Navigator | New EPIC | Medium | Depends on M05-27 |
| M05-30 | Skill adjacency matching: related skills in scoring | Scoring | EPIC-04 | High | AI sophistication |
| M05-31 | Semantic affinity matching: domain cluster scoring | Scoring | EPIC-04 | High | AI sophistication |
| M05-33 | Match explainability: direct vs semantic distinction | Explainability | EPIC-04 | Medium | Transparency |
| M05-34 | Match confidence indicator: visual confidence level | Explainability | EPIC-04 | Medium | UX enhancement |
| M05-37 | Feedback loop: reasons feed back into model weighting | Feedback Loop | EPIC-13 | Low | ML pipeline feedback |
| M05-39 | AI matching: offering-specific weight profiles | Configuration | EPIC-04 | Medium | Multi-tenancy configuration |
| M05-40 | Matching scope: search within ARPG first, then broaden | Matching Constraints | EPIC-04 | Medium | Organizational hierarchy scope |
| M05-41 | Matching scope: cross-region search for hard-to-fill | Matching Constraints | EPIC-04 | Medium | Global talent pool |
| M05-42 | Match result caching: avoid re-scoring unchanged pools | Performance | EPIC-04 | Low | Performance optimization |
| M05-44 | AI model versioning: track which model version produced match | Governance | EPIC-10 | High | Compliance and reproducibility |
| M05-45 | Phased AI adoption: Assist mode (suggestions only) | Adoption | New EPIC | High | Go-live strategy |
| M05-46 | Phased AI adoption: Recommend mode (ranked auto-shortlist) | Adoption | New EPIC | High | Maturity tier 2 |
| M05-47 | Phased AI adoption: Auto-assign mode (high-confidence) | Adoption | New EPIC | Medium | Maturity tier 3 |

---

## User Story → Business Requirement Mapping

| User Story | Epic | Business Requirement |
|-----------|------|---------------------|
| US-001 | EPIC-01 | BR-02 |
| US-002 | EPIC-01 | BR-02 |
| US-003 | EPIC-01 | BR-02 |
| US-004 | EPIC-01 | BR-02 |
| US-005 | EPIC-02 | BR-07 |
| US-006 | EPIC-03 | BR-EQF |
| US-007 | EPIC-03 | BR-EQF |
| US-008 | EPIC-03 | BR-EQF |
| US-009 | EPIC-04 | BR-01 |
| US-010 | EPIC-04 | BR-01 |
| US-011 | EPIC-04 | BR-01 |
| US-012 | EPIC-04 | BR-01 |
| US-013 | EPIC-04 | BR-01 |
| US-014 | EPIC-04 | BR-01 |
| US-015 | EPIC-04 | BR-03 |
| US-016 | EPIC-05 | BR-01, BR-03 |
| US-017 | EPIC-05 | BR-03 |
| US-018 | EPIC-05 | BR-03 |
| US-019 | EPIC-05 | BR-03 |
| US-020 | EPIC-06 | BR-04 |
| US-021 | EPIC-06 | BR-04 |
| US-022 | EPIC-06 | BR-04 |
| US-023 | EPIC-07 | BR-05 |
| US-024 | EPIC-07 | BR-05 |
| US-025 | EPIC-07 | BR-05 |
| US-026 | EPIC-07 | BR-05 |
| US-027 | EPIC-07 | BR-05 |
| US-028 | EPIC-07 | BR-05 |
| US-029 | EPIC-08 | BR-06 |
| US-030 | EPIC-08 | BR-06 |
| US-031 | EPIC-08 | BR-06 |
| US-032 | EPIC-09 | BR-08 |
| US-033 | EPIC-09 | BR-08 |
| US-034 | EPIC-09 | BR-08 |
| US-035 | EPIC-09 | BR-08 |
| US-036 | EPIC-09 | BR-08 |
| US-037 | EPIC-10 | BR-09 |
| US-038 | EPIC-10 | BR-09 |
| US-039 | EPIC-11 | BR-10 |
| US-040 | EPIC-11 | BR-10 |
| US-041 | EPIC-12 | BR-11 |
| US-042 | EPIC-12 | BR-11 |
| US-043 | EPIC-13 | BR-12 |
| US-044 | EPIC-14 | BR-13 |
| US-045 | EPIC-15 | BR-14 |
| US-046 | EPIC-16 | BR-15 |
| US-047 | EPIC-17 | BR-CPQ |
| US-048 | EPIC-17 | BR-CPQ |
| US-049 | EPIC-17 | BR-CPQ |
| US-050 | EPIC-17 | BR-CPQ |
| US-051 | EPIC-17 | BR-CPQ |
| US-052 | EPIC-17 | BR-CPQ |

---

## Epic → Feature Coverage Summary

| Epic | Stories | Features Covered | Gap Features |
|------|---------|-----------------|--------------|
| EPIC-01 | 4 | M05-32 (partial) | — |
| EPIC-02 | 1 | — | — |
| EPIC-03 | 3 | — | — |
| EPIC-04 | 7 | M05-01, M05-02, M05-04, M05-06, M05-10, M05-11, M05-15, M05-20, M05-29, M05-38 | M05-03, M05-05, M05-07, M05-08, M05-09, M05-17, M05-18, M05-24, M05-25, M05-26, M05-30, M05-31, M05-33, M05-34, M05-39, M05-40, M05-41, M05-42 |
| EPIC-05 | 4 | — | — |
| EPIC-06 | 3 | M05-19, M05-21, M05-22 | — |
| EPIC-07 | 6 | — | — |
| EPIC-08 | 3 | — | — |
| EPIC-09 | 5 | — | — |
| EPIC-10 | 2 | — | M05-16, M05-44 |
| EPIC-11 | 2 | — | — |
| EPIC-12 | 2 | — | — |
| EPIC-13 | 1 | M05-35, M05-36 (partial) | M05-37 |
| EPIC-14 | 1 | — | — |
| EPIC-15 | 1 | — | — |
| EPIC-16 | 1 | — | — |
| EPIC-17 | 6 | M05-43, M05-48 (partial) | — |
| **No Epic** | — | — | M05-12, M05-13, M05-14, M05-23, M05-27, M05-28, M05-45, M05-46, M05-47 |

---

## Recommended New Epics for Gap Features

| Proposed Epic | Features | Rationale |
|--------------|----------|-----------|
| EPIC-18: Match Readiness Framework | M05-12, M05-13, M05-14 | Automated routing tiers need a dedicated workflow |
| EPIC-19: Career Navigator | M05-23, M05-27, M05-28 | Employee-facing module, distinct from manager search |
| EPIC-20: Phased AI Adoption | M05-45, M05-46, M05-47 | Go-live strategy requires dedicated rollout planning |
