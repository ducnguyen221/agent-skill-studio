# Antigravity notes for Agent Skill Studio

Use `AGENTS.md` for shared repo instructions; refer to the Antigravity parts of `standards/HARNESSES.md` for Antigravity-specific setup. This file is **not** an instruction for other agent products.

For local discovery, project skills belong at `.agents/skills/<skill-name>/SKILL.md`. Canonical source remains in `skills/`; run `python3 studio.py install skills/skill-creator-studio --agent antigravity --user` to install for the user, or the same line with `--workspace .` instead of `--user` to install into this project. Avoid duplicating common rules here.

Check current Google documentation before changing migration-specific behavior; historic `.agent/` versus `.agents/` locations are version sensitive.
