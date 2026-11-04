# Custom Rules for Planning

Custom rules let you inject project-specific or personal conventions into the planning workflow (make, exec, plan-review). Rules are free-form markdown loaded at skill invocation time and applied as additional instructions alongside the skill's built-in behavior.

## File Locations

Two levels, checked in order (first-found-wins, never merged):

1. **Project-level**: `.opencode/planning-rules.md` in the current working directory
2. **User-level**: `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/data/cc-thingz/planning/planning-rules.md`

When both non-empty files exist, only the project-level file is used. Empty files are treated as absent and fall through to the next level.

## Resolution

Canonicalize the loaded skill base with `realpath` before traversing `../..` to the planning group root. Run its absolute `scripts/resolve-rules.sh` with argument `planning-rules.md`, through `shell` in the session's directory. Omitting the optional second data-directory argument selects the XDG/HOME default above. It outputs the first non-empty file or empty output when neither exists; errors must not be treated as absent rules. Review children receive resolved rules/source and absolute paths from their parent, not implicit parent context.

## Managing Rules

Ask the make command to manage rules:

- **show rules** — displays current rules and which level they came from
- **add/update project rules** — writes to `.opencode/planning-rules.md`
- **add/update user rules** — writes to the computed user path above
- **clear project rules** — deletes only `.opencode/planning-rules.md`
- **clear user rules** — deletes only the computed user file

## Example Content

```markdown
## testing conventions
- use table-driven tests with testify
- mock external dependencies with moq
- aim for 80% coverage minimum

## naming
- use camelCase for local variables
- keep function names under 30 characters

## plan structure preferences
- max 5 checkboxes per task
- always include rollback steps for migrations
```

## How Rules Apply

- **make**: rules influence plan structure, testing approach, naming conventions, task granularity
- **plan-review**: rules become additional review criteria for convention adherence
- **exec**: rules propagate to task subagents via the `USER_RULES` placeholder in task prompts

Rules supplement built-in instructions — they never replace them.
