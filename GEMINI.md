# Antigravity notes for Agent Skill Studio

Use `AGENTS.md` for shared repo instructions; refer to `adapters/ANTIGRAVITY_ADAPTER.md` for Antigravity-specific setup. This file is **not** an instruction for other agent products.

For local discovery, project skills belong at `.agents/skills/<skill-name>/SKILL.md`. Canonical source remains in `skills/`; run `python3 studio.py install skills/skill-creator-studio --agent antigravity --workspace .` when appropriate. Avoid duplicating common rules here.

Check current Google documentation before changing migration-specific behavior; historic `.agent/` versus `.agents/` locations are version sensitive.
