---
name: md-copy
description: Format final answer as markdown and copy to clipboard. Use when user says "copy as markdown", "md copy", "copy formatted", "clipboard", or wants the session's final answer formatted and copied.
---

# Markdown Copy

Extract the final answer from this session, convert it to proper markdown format, and copy to clipboard.

## Formatting Rules

1. **No heading elements** (`#`, `##`, etc.) — use **bold** for section titles instead
2. Convert any ASCII tables to proper markdown tables
3. Use *italic* for emphasis and minor notes
4. Preserve code blocks with proper language tags
5. Keep bullet lists and numbered lists
6. Remove any leading spaces or bullet headers (bullet-style)
7. Give the content a nice descriptive title (as bold text, not heading)

## Workflow

1. Identify the final answer/response in this session
2. Format it according to the rules above
3. Prepare the exact formatted UTF-8 content in a uniquely created private directory under `/tmp/opencode/` (e.g. Python `tempfile.mkdtemp(prefix="md-copy-", dir="/tmp/opencode")`). Use `patch` or a byte-preserving writer. Do not interpolate content in shell, use `echo`, add a heredoc newline inadvertently, or copy surrounding transport fences. Preserve code indentation; removing leading bullet headers applies to wrapper prose, not nested lists or code.
4. Canonicalize this loaded skill's base with `realpath`; the helper is `../../scripts/clipboard.py` relative to that canonical base. Run `python3 <absolute-helper> <absolute-prepared-file>` with argv/path quoting, then remove only this invocation's temporary files in a finally/cleanup step, including on failure. Do not use a global installed path.
5. Report success and the helper's character count only on exit 0. Missing backend or failed display connection is an error, not successful copying. Keep the formatted content available in the conversation if copying fails.

The helper prefers `wl-copy` on Wayland, preserves upstream macOS `pbcopy` and X11 `xclip -selection clipboard` / `xsel --clipboard --input` fallbacks, and copies the prepared bytes unchanged. Markdown is copied as literal UTF-8 text, not rendered HTML. It never reads the clipboard; no `wl-paste`, `pbpaste`, `xclip -o` or backup/restore of the user's selection. Testing is not permission to overwrite the actual clipboard: use isolated fixtures or a separately owned headless display unless the user explicitly approves a real test copy. Do not guess another user's display when service environment is stale.
