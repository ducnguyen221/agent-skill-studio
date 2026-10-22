---
name: writing-commit-messages
description: "Writes a Conventional Commits message from a staged diff. Use when the user asks for a commit message or to commit staged changes; not for changelogs or PR descriptions."
metadata:
  version: "1.0.0"
---

# Writing Commit Messages

Turns the staged diff into one Conventional Commits message, so history stays searchable and release tooling can read the change type. The message explains why the change was made, because the diff already shows what changed.

## Steps

1. Run `git diff --staged` and read the whole diff. Stop and ask if nothing is staged, because there is nothing to describe.
2. Pick the type (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`) and an optional scope that names the touched module.
3. Write a subject of at most 72 characters in the imperative mood, then a body that says why the change was needed.

## Gotchas

- Mark a breaking change with a `!` right before the colon (`feat!:`, `feat(api)!:`) or with a footer line `BREAKING CHANGE: <what breaks>`.
- Do not invent a ticket code. Add a `Refs:` footer only when the user or the branch name gave one.
