# Project entrypoint template

These files are starting points for **another target project**, not files to copy blindly over an existing repository.

- `AGENTS.md`: the one shared set of project rules; Codex reads it directly. Its `## Loading these rules` table says how each agent finds it.
- `CLAUDE.md`: Claude Code imports it with `@AGENTS.md`, so nothing is duplicated; adds the Claude skill folder and install line.
- `GEMINI.md`: Antigravity reads and follows `AGENTS.md`; adds the Antigravity skill folder and install line.

After applying, verify loaded instructions directly in each agent, because file discovery and instruction precedence vary by runtime. Skill installation into `.claude/skills/` or `.agents/skills/` is a separate operation.
