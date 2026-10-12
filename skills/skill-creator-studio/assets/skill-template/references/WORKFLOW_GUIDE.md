# Workflow Guide (template resource)

## Purpose

Use this file to specify domain knowledge, not to re-copy every line of the `SKILL.md` entrypoint.

## What to define for a real Skill

- Inputs: file/data types, schemas, access needs and prerequisites.
- Branches: identify important decisions (create versus edit, valid versus incomplete input).
- Validations: invariants that can be checked deterministically.
- Failure modes: expected errors and recommended recovery.
- Output contract: files, fields, quality requirements and reporting format.

## How to route it

Give this reference a clear name, link it directly from `SKILL.md`, and specify **when** to open it. If the reference eventually exceeds 100 lines, put a Contents list near the top.

## Examples

**Input:** Sales CSV with unique transaction IDs. **Process:** validate schema, duplicates and amounts. **Output:** quality report with issues and corrective options.

**Input:** A DAX measure request. **Process:** confirm date table assumptions before authoring measure. **Output:** syntactically plausible DAX with stated requirements; verify in target model before claiming it works.
