# EPIC-17: CPQ Pre-Sales Talent Preview

> **Priority:** P1 (Must)  
> **Sprint:** Backlog (pending CPQ integration timeline)  
> **Business Requirement:** BR-CPQ  
> **Total Story Points:** 24

## Summary

Integration with CPQ to auto-detect RFI/NSSR pre-sales requests, trigger talent previews, manage the pre-sales bench search, and support the handoff to staffing when a deal progresses. Includes audit trails and analytics for the pre-sales talent process.

## User Stories

| Story | Title | Points | Sprint | Status |
|-------|-------|--------|--------|--------|
| [US-047](../user-stories/US-047.md) | CPQ RFI/NSSR type detection | 3 | Backlog | New |
| [US-048](../user-stories/US-048.md) | Auto-trigger talent preview on qualifying RFI/NSSR | 5 | Backlog | New |
| [US-049](../user-stories/US-049.md) | Auto-convert talent preview to Resource Request on Stage 4B | 5 | Backlog | New |
| [US-050](../user-stories/US-050.md) | Pre-sales to staffing handoff | 3 | Backlog | New |
| [US-051](../user-stories/US-051.md) | Talent preview audit trail | 3 | Backlog | New |
| [US-052](../user-stories/US-052.md) | Talent preview analytics — response time and win rate | 5 | Backlog | New |

## Dependencies

- **Upstream:** CPQ system integration, EPIC-04 (search engine), EPIC-05 (CV generation)
- **Downstream:** None

## Acceptance Criteria (Epic Level)

- CPQ opportunity type (RFI/NSSR/other) auto-classified
- Talent preview auto-triggered for qualifying opportunities
- Auto-conversion to Resource Request on Stage 4B deal progression
- Pre-sales candidate selections carry forward to staffing
- Immutable audit trail for all talent previews
- Analytics dashboard: response time, preview count, win rate correlation
