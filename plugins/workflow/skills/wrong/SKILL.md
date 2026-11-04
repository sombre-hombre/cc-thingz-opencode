---
name: wrong
description: Reset and re-evaluate when current approach isn't working. Use when user says "wrong", "this isn't working", "wrong approach", "start over", "try again", "bad direction", or when the current solution path has hit a dead end and needs a fresh perspective.
---

# Wrong — Reset and Re-evaluate

The current approach isn't working as expected. Step back and re-examine the problem from the beginning.

## Workflow

### Step 1: Re-analyze the Core Problem

State the problem in clear, simple terms. What exactly are we trying to solve?

### Step 2: Identify Missing Context

Determine what additional information is needed about:
- The existing codebase and its patterns
- Performance requirements or constraints
- Integration points with other systems
- Expected usage patterns or scale
- Any domain-specific requirements not yet mentioned

Investigate the relevant code, configuration, tests and prior failed attempts with `read`, `grep`, `glob` and bounded `shell` probes. Separate verified facts from hypotheses; do not merely restate the previous solution or assume a bug rather than a misunderstanding. Ask only missing clarifying questions using the available `question` tool or explicit chat fallback before proceeding; carry forward already confirmed constraints.

### Step 3: Propose Fresh Approaches

Suggest 2-3 alternative solutions that:
- Follow project best practices and idioms
- Match the existing code's style and architecture patterns
- Are maintainable and testable
- Solve the exact problem without over-engineering
- Don't use shortcuts or hacks

### Step 4: Explain Trade-offs

For each proposed approach, briefly explain:
- Why this approach fits the problem
- What the main benefits and drawbacks are
- How it integrates with the existing codebase

### Step 5: Recommend the Best Path Forward

Which approach is most appropriate and why?

### Step 6: Confirm and Hand Off to Planning

After the user selects/confirms the approach, load `skill({id: "make"})` in this session. Pass the core problem, investigation/evidence paths, failed approaches and why they failed, 2–3 fresh alternatives and trade-offs, chosen approach, scope, constraints, test/edge-case requirements and already answered questions as data. Make fills only remaining gaps. Do not implement from this reset alone, execute slash text in shell, or pretend a mention invokes a skill.

If native Plan is chosen, the user selects it in their client; no `EnterPlanMode` tool exists. After saving, use the explicit user `/review-plan <absolute-path>` entrypoint or load make's review-only workflow. Missing planning capability leaves a pending handoff, not a fabricated plan/approval. Re-evaluation never authorizes discarding existing edits or resetting Git state.

## Requirements

- Solution must be production-ready, not a proof of concept
- Code should be idiomatic and follow established patterns
- Include comprehensive tests with edge cases
- Provide complete, runnable code with no placeholders
- Ensure the solution is maintainable

**Ask missing clarifying questions before proceeding; do not repeat already answered questions or treat an unresolved choice as permission to implement.**
