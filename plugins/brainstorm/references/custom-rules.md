# Custom Rules for Brainstorm

Custom rules let you inject project-specific or personal conventions into the brainstorm workflow. Rules are free-form markdown loaded at skill invocation time and applied as additional instructions alongside the skill's built-in behavior.

## File Locations

Two levels, checked in order (first-found-wins, never merged):

1. **Project-level**: `.opencode/brainstorm-rules.md` in the current working directory
2. **User-level**: `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/data/cc-thingz/brainstorm/brainstorm-rules.md`

When both non-empty files exist, only the project-level file is used. Empty files are treated as absent and fall through to the next level.

## Resolution

Canonicalize the loaded skill base with `realpath` before traversing `../..` to the brainstorm group root. Run its absolute `scripts/resolve-rules.sh` with the single argument `brainstorm-rules.md`, through `shell` in the session's directory. An optional explicit data-directory argument replaces the XDG/HOME user location. Empty output means no rules; a failed call is not absence. Pass decisions, design, resolved rules/source and unanswered questions to make in the current session.

## Managing Rules

Ask the brainstorm skill to manage rules:

- **show rules** — displays current rules and which level they came from
- **add/update project rules** — writes to `.opencode/brainstorm-rules.md`
- **add/update user rules** — writes to the computed user path above
- **clear project rules** — deletes only `.opencode/brainstorm-rules.md`
- **clear user rules** — deletes only the computed user file

## Example Content

```markdown
## design preferences
- prefer simple solutions over clever abstractions
- always consider backward compatibility
- propose at most 3 approaches

## technology constraints
- backend must be Go with standard library where possible
- frontend uses HTMX, avoid JavaScript frameworks
- database is SQLite via sqlx

## naming conventions
- use camelCase for variables
- use PascalCase for exported types
```

## How Rules Apply

Rules influence design preferences, naming conventions, technology choices, and other aspects of the brainstorm dialogue. They supplement built-in instructions — they never replace them.
