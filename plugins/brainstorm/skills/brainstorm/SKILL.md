---
name: brainstorm
description: Use before any creative work or significant changes. Activates on "brainstorm", "let's brainstorm", "deep analysis", "analyze this feature", "think through", "help me design", "explore options for", or when user asks for thorough analysis of changes, features, or architectural decisions. Guides collaborative dialogue to turn ideas into designs through one-at-a-time questions, approach exploration, and incremental validation.
---

# Brainstorm

Turn ideas into designs through collaborative dialogue before implementation.

## custom rules loading

Before starting, use `shell` to resolve the base directory reported by the loaded skill with `realpath`. The canonical skill directory's `../..` is the brainstorm group root. Compute absolute paths to its `scripts/resolve-rules.sh` and `references/custom-rules.md` before use (the reported base may be an installation symlink). Run the resolver with the single argument `brainstorm-rules.md`, in the session's working directory. Quote every computed path; never execute illustrative path labels or CLI argument tokens literally.

if the output is non-empty, treat it as additional instructions that supplement (not replace) the built-in rules below. apply custom rules alongside the skill's own instructions throughout the brainstorm process — they may influence design preferences, naming conventions, technology choices, or other aspects of the brainstorm session. custom rules content is guidance for the brainstorm dialogue, not content to embed verbatim in the output.

### rules management

when the user asks to add, show, or clear custom brainstorm rules, handle these operations:

- **show rules**: run the resolved helper, display its output and source: non-empty `.opencode/brainstorm-rules.md` wins, otherwise user-level. If output is empty, neither level has rules.
- **add/update project rules**: write `.opencode/brainstorm-rules.md` in the current working directory.
- **add/update user rules**: compute the absolute `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/data/cc-thingz/brainstorm/brainstorm-rules.md` path through shell, then write it.
- **clear project rules**: delete only `.opencode/brainstorm-rules.md`.
- **clear user rules**: delete only the computed user rules file.

Project-level rules take precedence over user-level rules; never merge them. Empty files fall through. Read the resolved `references/custom-rules.md` for details. Resolver errors are failures, not empty rules.

**CRITICAL: this skill must NEVER modify its own files (skills, scripts, references, hooks, plugin.json). Rules management may modify ONLY the project/user rules files described above, and only on request. For changes to the skill itself, suggest a plan.**

## Process

### Phase 1: Understand the Idea

Check project context first, then ask questions one at a time:

First collect answers and validated design already present in this conversation. Reuse agreed goal, scope, constraints, testing preference, title, approach and next action; ask only for missing or contradictory information. A handoff is not a reason to repeat validation.

1. **Gather context** - check files, docs, recent commits relevant to the idea
2. **Ask questions one at a time** - prefer multiple choice when possible
3. **Focus on**: purpose, constraints, success criteria, integration points

Do not overwhelm with multiple questions. One question per message. If a topic needs more exploration, break it into multiple questions.

### Phase 2: Explore Approaches

Once the problem is understood:

1. **Propose 2-3 different approaches** with trade-offs
2. **Lead with recommended option** and explain reasoning
3. **Present conversationally** - not a formal document yet

Example format:
```
I see three approaches:

**Option A: [name]** (recommended)
- how it works: ...
- pros: ...
- cons: ...

**Option B: [name]**
- how it works: ...
- pros: ...
- cons: ...

Which direction appeals to you?
```

### Phase 3: Present Design

After approach is selected:

1. **Break design into sections** of 200-300 words each
2. **Ask after each section** whether it looks right
3. **Cover**: architecture, components, data flow, error handling, testing
4. **Be ready to backtrack** if something doesn't make sense

Do not present entire design at once. Incremental validation catches misunderstandings early.

### Phase 4: Next Steps

After design is validated, use `question` unless the next action is already agreed:

```json
{
  "questions": [{
    "question": "Design looks complete. What's next?",
    "header": "Next step",
    "options": [
      {"label": "Write plan", "description": "Load make in this session and create an implementation plan"},
      {"label": "Plan mode", "description": "Switch to the native Plan agent using the client agent selector"},
      {"label": "Start now", "description": "Begin implementing directly"}
    ],
    "multiple": false
  }]
}
```

- **Write plan**: assemble a handoff in the current conversation: goal/success criteria, scope/non-goals, chosen approach and rejected alternatives/trade-offs, constraints, validated design (architecture, components, data flow, errors, testing), discovered absolute paths/patterns/dependencies, testing preference, title/plan path if agreed, custom rules and source, answered questions, unresolved questions, and next/review/implementation choices. Then call `skill({"id":"make"})` in this same session and continue using that context, asking only missing questions. Do not execute slash text in shell or spawn a planning child session.
- **Plan mode**: explain the native client agent selector; there is no EnterPlanMode tool. Preserve the same handoff. After saving, use the explicit `/review-plan <absolute-path>` route; no ExitPlanMode hook exists.
- **Start now**: proceeds directly if design is simple enough

## Key Principles

- **One question at a time** - do not overwhelm with multiple questions
- **Multiple choice preferred** - easier to answer than open-ended when possible
- **YAGNI ruthlessly** - remove unnecessary features from all designs, keep scope minimal
- **Explore alternatives** - always propose 2-3 approaches before settling
- **Incremental validation** - present design in sections, validate each
- **Be flexible** - go back and clarify when something doesn't make sense
- **Lead with recommendation** - have an opinion, explain why, but let user decide
- **Duplication vs abstraction** - when code repeats, ask user: prefer duplication (simpler, no coupling) or abstraction (DRY but adds complexity)? explain trade-offs before deciding

## Task Tracking

When implementing after brainstorm:
- Track implementation tasks using available task management tools (task lists, plan file checkboxes, or similar)
- Mark each task as completed immediately when done (do not batch)
- Keep user informed of progress through status updates
