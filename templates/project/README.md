# Project entrypoint template

These files are starting points for **another target project**, not files to copy blindly over an existing repository.

- `AGENTS.md`: shared project instructions for Codex and runtimes that support it.
- `CLAUDE.md`: Claude Code can import `@AGENTS.md` to reduce duplicate maintenance.
- `GEMINI.md`: Antigravity-specific notes; it may also load AGENTS.md, so do not repeat all shared content.

After applying, verify loaded instructions directly in each agent, because file discovery and instruction precedence vary by runtime. Skill installation into `.claude/skills/` or `.agents/skills/` is a separate operation.
