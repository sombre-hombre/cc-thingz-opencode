---
name: learn
description: Capture strategic session knowledge in scope-appropriate AGENTS.md or explicitly configured local instructions, respecting existing memory-placement guidance. Use when user says "learn", "save knowledge", "update agents.md", "capture learnings", or at end of significant work sessions. Also used for pre-commit knowledge capture.
---

# Learn

Review the current conversation history and identify strategic, reusable project knowledge. Use scope-appropriate `AGENTS.md` for shared knowledge and an explicitly configured local instruction file for genuinely personal or environment-specific discoveries. Never assume `AGENTS.local.md` is automatically loaded.

## Analysis Process

1. **Review Session History**
   - Examine all files read and modified during this session
   - Identify patterns discovered while working on tasks
   - Note architectural insights gained from exploring the codebase

2. **Extract Strategic Knowledge**
   - Filter out tactical details (bug fixes, specific implementations)
   - Focus on reusable patterns and project structure
   - Identify conventions and architectural decisions

3. **Categorize Findings**
   - Project architecture and structure
   - Data flow patterns
   - External service integrations
   - Project-specific conventions
   - Key dependencies and their purposes
   - Configuration patterns
   - Testing strategies
   - Build and deployment processes
   - Operational knowledge (debugging, DevOps)

## Destinations

First follow existing project/user memory-placement guidance; the following are defaults only:

- **`AGENTS.md`** (committed, team-shared) — repository root for project-wide knowledge, or the existing nearest applicable nested `AGENTS.md` for component-specific knowledge. Check the affected paths and actual instruction scope; do not put repository-wide rules in a narrow subtree or broaden a component rule to the whole repo. If no suitable file exists, propose the appropriate project path before creating it.
- **An explicitly configured local instruction file** — used only when **both** conditions hold:
  1. The file is already connected by OpenCode's `instructions` configuration and is intended for local knowledge. An existing, ignored `AGENTS.local.md` alone is NOT opt-in. Use known instruction sources or inspect only relevant `instructions` entries, never dump config/secrets or assume every markdown file is loaded.
  2. The discovery describes per-developer / per-checkout state — not just *mentions* something personal, but the knowledge itself is meaningful only to the current developer on this machine. Examples: a tool-loading workaround that depends on this developer's interpreter / runtime setup, a personal alias, a per-checkout env override.

  **Counter-example:** *"We keep credentials in `~/.aws/credentials`"* mentions a user-home path but describes a team-wide convention — the path is illustrative, not per-developer state. Such notes belong in scope-appropriate `AGENTS.md`. Ambiguous reusable project knowledge defaults there, not into hidden local notes. Never store credentials themselves.

If genuinely personal knowledge has no connected local destination, offer to choose/connect a local file, or skip it. Do not create `AGENTS.local.md`, change configuration, or put personal state into shared `AGENTS.md` silently. Connection/config changes require explicit permission and readback; saving knowledge is not blanket permission to change configuration.

Never write global user memory (`<config>/AGENTS.md`, home-level instructions, or global configured files) in this skill. Read already applicable guidance to avoid duplicating cross-project knowledge; do not recursively scan private user directories. A project-configured local file must also be an authorized project/local destination, not a globally shared file merely referenced by the project.

## What Qualifies

**INCLUDE** - Strategic discoveries from this session:
- Architectural patterns uncovered while working
- Project structure insights gained from navigation
- Conventions noticed across multiple files
- Integration patterns discovered
- Configuration approaches identified
- Testing strategies observed
- Build/deployment processes encountered
- Performance optimizations found
- Security implementations discovered
- Operational knowledge:
  - Database locations and connection details per environment
  - Useful queries discovered during debugging
  - Testing procedures and verification steps
  - Deployment workflows and commands
  - Log locations and monitoring endpoints
  - Environment-specific quirks and gotchas

**EXCLUDE** - Session-specific tactical work:
- The specific bug we fixed
- The particular feature we implemented
- Temporary workarounds we used
- One-off code changes
- TODO items we encountered
- Historical context about changes

## Decision Criteria

Ask yourself for each discovery:
- "Will this help understand the project in 6 months?"
- "Is this a pattern that appears multiple times?"
- "Does this represent a project-wide convention?"
- "Would knowing this speed up future development?"
- "Would this save debugging time in the future?" (for operational knowledge)

## Workflow

### 1. Check for Existing Memory-Placement Guidance
Before applying defaults, read applicable root/nested `AGENTS.md` and explicitly configured instructions, including already supplied user guidance, for memory-placement rules — e.g. a placement decision tree, project-specific triage workflow, or dedicated knowledge files. Defer to those rules rather than overriding them. OpenCode combines instruction sources; do not invent a last-file-wins precedence. Conflicting placement guidance needs clarification before writing. Do not discover Claude rules or treat arbitrary local files as instructions.

### 2. Check Existing Memory Content
Read the selected project destinations and applicable configured local instructions to avoid duplication, including knowledge already supplied in user guidance. Respect scope and preserve unrelated content.

### 3. Early Exit if Nothing Found
If no new strategic knowledge was discovered during this session:
- Report "no new strategic knowledge to capture"
- Do NOT ask a question
- End the skill execution

### 4. Classify Each Discovery
Classify each discovery separately using [Destinations](#destinations). Show the actual path and scope. Personal items without a connected local destination remain pending or skipped, never silently rerouted.

### 5. New Knowledge to Add
Present discovered knowledge formatted for the chosen destination, tagging each block with its inferred file:
```markdown
## [Section Name] → packages/service/AGENTS.md (service scope)
- Discovery 1
- Discovery 2
```

### 6. Granular User Confirmation

**CRITICAL**: Use the available `question` tool (`multiple: true` for multi-selection) for granular selection, or ask explicitly in chat if unavailable. Never write before confirmation. A prior explicit selection in the current request can satisfy this gate; do not ask it again. If interactive questions are prohibited, report pending choices without saving.

Build options dynamically based on discoveries:
- First option: "All knowledge" - save everything to its inferred destination
- Last option before custom: "None" - skip saving entirely
- Middle options: Individual knowledge items (up to 2-3 most significant), each labelled with its inferred destination
- User can always type custom selection via "Other"

Example with 3 discoveries (2 project, 1 personal):
```yaml
question: "Which knowledge should I save?"
options:
  - label: "All (3 items)"
    description: "Save all discovered patterns to their inferred destinations"
  - label: "Service discovery pattern → packages/service/AGENTS.md"
    description: "Service-scoped convention for how its modules find each other"
  - label: "Local toolchain variant → configured local-rules.md"
    description: "Per-checkout build runner override (only relevant on this machine)"
  - label: "None"
    description: "Skip saving, nothing worth keeping"
```

Example with 1 discovery:
```yaml
question: "Save this knowledge?"
options:
  - label: "Yes → AGENTS.md"
    description: "Save: [brief description of the discovery]"
  - label: "No"
    description: "Skip saving"
```

After user selection:
- "All" -> save everything to its inferred destination
- "None" -> end without saving
- Specific item -> save only that item, to the inferred destination shown in the label
- "Other" -> user types custom selection of **which discoveries** to save (comma-separated item names). Destinations follow the labels shown — `"Other"` does NOT redirect a destination to an arbitrary path. To override a routing decision, the user should decline the auto-classification, edit the destination file manually, or re-invoke the skill with explicit instructions.

If All and None or individual selections conflict, clarify rather than guess. Apply only selected items with `patch`, read back each destination, and report saved paths and pending/skipped items. Do not auto-commit.

"All" never authorizes connecting a missing local destination or writing a pending personal item into shared memory; resolve that destination with separate explicit permission or leave the item pending.

## Important Guidelines
- Only capture genuinely new discoveries from this session
- Don't duplicate existing project or configured instruction content
- Focus on patterns observed, not specific code written
- Keep descriptions concise and actionable
- MUST obtain granular confirmation using the available V2 question interface or explicit chat fallback
- If no knowledge found, exit early without asking
- **Defer to project- or user-level memory-placement guidance discovered in step 1** — do not override existing conventions with this skill's defaults
