# EPIC-02: Integration with FDS / My Growth

> **Priority:** P1 (Must)  
> **Sprint:** Sprint 1  
> **Business Requirement:** BR-07  
> **Total Story Points:** 3

## Summary

Ingest FDS knowledge data from the My Growth platform via APIs to consolidate talent knowledge before enabling searches. My Growth provides supplementary skill and knowledge data that enriches employee profiles beyond what Workday captures.

## User Stories

| Story | Title | Points | Sprint | Status |
|-------|-------|--------|--------|--------|
| [US-005](../user-stories/US-005.md) | Ingest My Growth knowledge data via API | 3 | Sprint 1 | New |

## Dependencies

- **Upstream:** My Growth API access and data schema
- **Downstream:** EPIC-04 (search uses enriched data), EPIC-07 (dashboards show consolidated view)

## Acceptance Criteria (Epic Level)

- FDS knowledge data ingested via API and linked to correct employee IDs
- Data stored and searchable within TalentIQ
