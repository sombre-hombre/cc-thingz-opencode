# Contributor instructions

- Preserve the upstream workflows, MIT license and attribution in `upstream.lock`.
- Target OpenCode V2. Use https://opencode.ai/v2/docs/ as the API reference.
- Keep runtime helpers compatible with Linux and macOS. Do not assume GNU tools,
  a particular home directory, display server, terminal or executable location.
- Use Python 3.10+ and Bash 3.2+ unless a higher requirement is documented.
- Validate changes with `bash tests/run.sh`. Tests must use isolated HOME/XDG
  directories; never modify the contributor's actual OpenCode configuration.
- Preserve foreign files and staged changes. Use explicit paths for commits.
- Do not publish comments, releases or merges, change the clipboard, open terminal
  windows or call paid models during automated tests without explicit permission.
- Keep local reports, model transcripts, credentials, session identifiers and
  installation backups out of this repository. Use synthetic fixtures in tests.
- Distinguish fixture tests, actual platform tests and manual checks in reports.
- Keep supporting scripts beside their skills and resolve paths dynamically.
