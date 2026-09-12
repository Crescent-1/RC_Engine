# Project instructions for Codex

Read `CLAUDE.md` for the project's operating rules and `codex.md` for recent
changes before starting work. Follow those rules alongside the user's current
instructions.

## Keep the change log current

Whenever you change project files, update the root `codex.md` before finishing
the task. This includes code, configuration, tests, documentation and generated
deliverables. A read-only review or discussion does not require a change entry.

- Add a dated entry at the top of the change history, using Asia/Calcutta time.
- Summarize what changed, why, and the main files or areas affected.
- Record checks actually run and their results, plus any unresolved limitations.
- Include a commit hash when available; otherwise say the changes are uncommitted.
  Do not create a commit solely to populate the log or record a commit's own hash
  inside itself. A later update can fill in a known hash.
- Preserve previous entries. Correct inaccurate information explicitly rather
  than silently rewriting the history.
- Keep entries concise. Never include credentials, environment secrets or full
  client passage text.

The log is part of completing the change, not a separate task the user needs
to request each time.
