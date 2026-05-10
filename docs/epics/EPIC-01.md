# EPIC-01: Workday Data Integration

> **Priority:** P1 (Must)  
> **Sprint:** Sprint 1–2  
> **Business Requirement:** BR-02  
> **Total Story Points:** 10

## Summary

Integration with Workday to retrieve employee attributes and CV artifacts as the authoritative data source for the platform. Workday is the system of record for employee skills, certifications, languages, job level, location, service line, and manager data. CV artifacts stored in Workday are retrieved for processing and generation.

## User Stories

| Story | Title | Points | Sprint | Status |
|-------|-------|--------|--------|--------|
| [US-001](../user-stories/US-001.md) | Candidate attributes from Workday | 3 | Sprint 1 | New |
| [US-002](../user-stories/US-002.md) | Retrieve CV artifact from Workday | 2 | Sprint 1 | New |
| [US-003](../user-stories/US-003.md) | Show data source (Workday vs CV repository) | 2 | Sprint 2 | New |
| [US-004](../user-stories/US-004.md) | Integration with production quality data | 3 | Sprint 1 | New |

## Dependencies

- **Upstream:** Workday API access, production credentials
- **Downstream:** EPIC-03 (EQF/MECES mapping depends on Workday education data), EPIC-04 (search depends on Workday attributes), EPIC-05 (CV generation depends on CV artifacts)

## Acceptance Criteria (Epic Level)

- All employee attributes flow from Workday to TalentIQ
- CV artifacts retrievable from Workday when available
- Data provenance (Workday vs CV) visible in the UI
- Works with production-quality data, not UAT/simulated
