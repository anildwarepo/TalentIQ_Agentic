# EPIC-11: Soft Hold (Optional)

> **Priority:** P3 (Could)  
> **Sprint:** Backlog  
> **Business Requirement:** BR-10  
> **Total Story Points:** 4

## Summary

Soft hold/pause candidates for specific deals or projects with transparent history. Includes configurable auto-expiry to prevent indefinite reservations and maintain bench accuracy.

## User Stories

| Story | Title | Points | Sprint | Status |
|-------|-------|--------|--------|--------|
| [US-039](../user-stories/US-039.md) | Soft hold candidate for a specific deal with auto-expiry | 3 | Backlog | New |
| [US-040](../user-stories/US-040.md) | Release soft hold and keep history | 1 | Backlog | New |

## Dependencies

- **Upstream:** EPIC-04 (search results), EPIC-10 (permissions for soft hold)
- **Downstream:** None

## Acceptance Criteria (Epic Level)

- Candidates can be soft-reserved with who/when/why metadata
- Auto-expiry releases hold after configurable period (default admin-set)
- Manager and hold owner notified 48 hours before expiry
- Full hold history maintained
