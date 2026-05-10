# Agent Handoff Orchestration

## Pattern: Two-Phase Flow with Agent-as-Tool

When a child agent needs user input mid-workflow (e.g., template selection before CV generation):

1. The child agent CANNOT pause — it runs to completion and returns text
2. Phase 1: Child returns a selection prompt (no action taken)
3. The triage (parent) agent relays the prompt to the user
4. Phase 2: User replies → triage must reconstruct full context from its own chat history and handoff again
5. **Reliability issue:** LLMs don't reliably extract context from history for the second handoff
6. **Solution:** Code-level augmentation in the API layer — `_augment_cv_template_choice()` rewrites short user replies before they enter chat history

## Key Rules
- `propagate_session=True` passes `AgentSession` to child agents but does NOT share parent's conversation history
- Each `as_tool()` invocation is independent — the child only sees the message passed to it
- The parent (triage) keeps its own history via `InMemoryHistoryProvider`
- For multi-step flows: either do everything in one call (generate with default, offer alternatives) or manage state in the API layer

## Confidence: medium
