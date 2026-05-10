# EPIC-06: Certifications and Test Handling

> **Priority:** P1 (Must)  
> **Sprint:** Sprint 4  
> **Business Requirement:** BR-04  
> **Total Story Points:** 9

## Summary

Manage certification validity status and download certification test documents for bid submissions. Includes packaging certification tests with bundled candidate profiles for response packages.

## User Stories

| Story | Title | Points | Sprint | Status |
|-------|-------|--------|--------|--------|
| [US-020](../user-stories/US-020.md) | View certification validity status | 2 | Sprint 4 | New |
| [US-021](../user-stories/US-021.md) | Download certification test documents | 2 | Sprint 4 | New |
| [US-022](../user-stories/US-022.md) | Package certification tests and bundled candidate profiles | 5 | Sprint 4 | New |

## Dependencies

- **Upstream:** EPIC-01 (certification data from Workday), EPIC-04 (search/shortlist feeds packaging)
- **Downstream:** EPIC-07 (dashboard certification views), EPIC-08 (certification expiry notifications)

## Acceptance Criteria (Epic Level)

- Certification status (valid/expiring/expired) visible per candidate
- Test documents downloadable when evidence exists
- Response packages bundle candidate profiles with certification evidence
- Packages are named, saved, retrievable, editable, duplicable, and exportable
