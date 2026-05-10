# EPIC-08: Automation and Notifications

> **Priority:** P1 (Must)  
> **Sprint:** Sprint 5  
> **Business Requirement:** BR-06  
> **Total Story Points:** 7

## Summary

Automatic reminder campaigns for CV updates and certification renewals with full audit trail. Managers can trigger campaigns targeting employees who exceed freshness thresholds or have expiring/expired certifications.

## User Stories

| Story | Title | Points | Sprint | Status |
|-------|-------|--------|--------|--------|
| [US-029](../user-stories/US-029.md) | Trigger automatic CV update reminder campaigns | 3 | Sprint 5 | New |
| [US-030](../user-stories/US-030.md) | Trigger reminders for expired/upcoming certifications | 2 | Sprint 5 | New |
| [US-031](../user-stories/US-031.md) | Audit trail of reminder campaigns | 2 | Sprint 5 | New |

## Dependencies

- **Upstream:** EPIC-01 (CV freshness data), EPIC-06 (certification expiry data), EPIC-07 (dashboards identify who needs reminders)
- **Downstream:** None

## Acceptance Criteria (Epic Level)

- CV update campaigns target only employees exceeding freshness threshold
- Certification campaigns target only employees with expired certifications
- Full audit trail: date/time, target group size, recipients
