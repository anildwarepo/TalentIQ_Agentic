# EPIC-04: Candidate Search & CV Search

> **Priority:** P1 (Must)  
> **Sprint:** Sprint 3–4  
> **Business Requirement:** BR-01, BR-03  
> **Total Story Points:** 32

## Summary

Search for internal candidates using multiple criteria (skills, certifications, languages, location, job level, service line, MECES/EQF level) and perform full-text metasearch on CV content stored in Workday. Includes multi-position bid sessions, result triage, export functionality, skill gap identification, and impressiveness scoring. CV viewing and generation is covered in EPIC-05.

## User Stories

| Story | Title | Points | Sprint | Status |
|-------|-------|--------|--------|--------|
| [US-009](../user-stories/US-009.md) | Search candidates with multiple criteria, certifications and impressiveness scoring | 8 | Sprint 3 | New |
| [US-010](../user-stories/US-010.md) | Apply additional filters on top of search results | 3 | Sprint 3 | New |
| [US-011](../user-stories/US-011.md) | Define multiple positions in a single bid search session | 3 | Sprint 3 | New |
| [US-012](../user-stories/US-012.md) | Show triage attributes in search results | 2 | Sprint 3 | New |
| [US-013](../user-stories/US-013.md) | Export shortlist/search results to Excel, CSV, PDF or PPTX | 5 | Sprint 3 | New |
| [US-014](../user-stories/US-014.md) | Identify skill gaps and suggest employees for retraining | 5 | Sprint 4 | New |
| [US-015](../user-stories/US-015.md) | Full text search on employee resume content | 3 | Sprint 4 | New |

## Dependencies

- **Upstream:** EPIC-01 (Workday data), EPIC-02 (My Growth data), EPIC-03 (EQF/MECES levels), EPIC-10 (RBAC)
- **Downstream:** EPIC-05 (CV generation from search results), EPIC-06 (certification packages), EPIC-07 (dashboards)

## Feature Coverage (from features.csv)

**Covered:** M05-01, M05-02, M05-04, M05-06, M05-10, M05-11, M05-15, M05-20, M05-29, M05-38

**Gaps (need new stories):** M05-03 (availability), M05-05 (cost), M05-07 (engagement history), M05-08 (client familiarity), M05-09 (bench duration), M05-17 (bench-first), M05-18 (bench aging), M05-24 (comparison view), M05-25 (RM notes), M05-26 (status tracking), M05-30 (skill adjacency), M05-31 (semantic affinity), M05-33 (explainability detail), M05-34 (confidence indicator), M05-39 (offering-specific weights), M05-40 (ARPG scope), M05-41 (cross-region), M05-42 (caching)

## Acceptance Criteria (Epic Level)

- Multi-criteria search with combined skills/certifications
- Progressive filtering without re-running search
- Multi-position bid sessions with separate filter sets
- Impressiveness scoring with configurable weights
- Export to .xlsx, .csv, .pdf, .pptx with DXC branding
- Skill gap identification with training suggestions
- Full-text search on CV content
