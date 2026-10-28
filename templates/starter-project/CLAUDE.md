# Claude Code project instructions

@AGENTS.md

Use shared repo rules from the imported AGENTS.md. For Claude Code-specific Skills use `.claude/skills/<name>/SKILL.md`; install: `python studio.py install <skill> --agent claude --workspace .` (the engine has no per-user install for Claude: `--user` exits 2). If a task requires hooks, verify the version and configure/test Claude Code hooks separately; do not put vendor fields in portable Skill manifests.
