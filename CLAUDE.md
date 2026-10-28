# Claude Code adapter for Agent Skill Studio

@AGENTS.md

Apply the repo's shared rules from AGENTS.md and the relevant resources it routes to. For Claude Code-specific semantics, consult the Claude Code parts of `standards/HARNESSES.md`.

Claude project Skill discovery uses `.claude/skills/<skill-name>/SKILL.md`; canonical source lives under `skills/` in this repository. Explicitly install with `python3 studio.py install skills/skill-creator-studio --agent claude --workspace .` before expecting `/skill-creator-studio` to be discoverable (the engine has no per-user install for Claude: `--user` exits 2). This file alone does not install the skill.

Claude-only frontmatter features such as `hooks`, `disable-model-invocation`, `context: fork` or `paths` must not be added to portable Skill source files. If required, generate and test an isolated Claude-targeted variant.
