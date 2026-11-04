---
name: txt-copy
description: Copy generated text content to clipboard. Use when user asks to "copy this", "copy to clipboard", "save to clipboard", or after creating emails, messages, letters, or other text content that needs to be shared.
---

# Copy Text to Clipboard

Copy generated text content to clipboard via a unique private temp file. Preserve the selected text exactly: no Markdown conversion, title, wrapper, newline normalization, trimming, or trailing newline added by the transport.

## Activation Triggers

- "copy this", "copy to clipboard", "save to clipboard"
- "copy the email", "copy the message", "copy the letter"
- After generating text content when user indicates they want to use it
- "I need to paste this", "put it in clipboard"

## Workflow

1. Identify the text content to copy (from recent generation or user-specified)

2. Create a unique private directory under `/tmp/opencode/` (e.g. Python `tempfile.mkdtemp(prefix="txt-copy-", dir="/tmp/opencode")`), then write the selected UTF-8 content with `patch` or a byte-preserving writer. Never interpolate content in shell, use `echo`, or rely on a heredoc that adds an unwanted final newline. If the selection is ambiguous, clarify before copying; do not include the assistant's surrounding commentary.

3. Canonicalize this loaded skill's base with `realpath`. Resolve `../../scripts/clipboard.py` relative to that canonical base and run `python3 <absolute-helper> <absolute-file>` with properly quoted paths/argv. The helper prefers `wl-copy` on Wayland, retains macOS `pbcopy`, then X11 `xclip -selection clipboard` / `xsel --clipboard --input`. It sends the exact prepared bytes and never reads a selection. On backend failure do not silently switch to a different display/backend.

4. In a finally/cleanup step remove only this invocation's temporary files, including on failure. Confirm "Copied to clipboard (N characters)" only after exit 0, using the helper's count. A missing backend or connection failure must be reported clearly, with no false success. Keep the original text in the conversation if copying fails.

## Notes

- Tests use isolated fixtures or a separately owned headless display. Do not read, back up, restore, or overwrite the user's actual clipboard for a test absent explicit permission.
- Never invoke `wl-paste`, `pbpaste`, `xclip -o` or guess display sockets. If the service's display environment is stale, obtain the explicitly chosen client target before retrying.
- A normal explicit user copy request authorizes copying that selected content, not reading existing clipboard data.
