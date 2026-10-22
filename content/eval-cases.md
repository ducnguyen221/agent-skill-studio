# Mẫu case eval

> **Kết luận:** ba case mẫu cho skill `writing-commit-messages` (một typical, một edge, một near-miss), viết đúng dạng `evals/<skill>/cases.json`, kèm bản xuất agentskills viết tay. Đây là mẫu để chép và sửa, không phải eval đã chạy trên model (`not_run`).

Cách dùng: đặt các khối JSON dưới đây vào mảng `cases` của `evals/<skill>/cases.json` (đối tượng gốc có `skill_name` và `cases`), tạo các file trong `fixtures` cạnh đó, rồi chạy `studio.py evals <skill>`. Quy tắc: [EVALUATION_STANDARD.md](../standards/EVALUATION_STANDARD.md) và `SK-11`. Fixture của mẫu này không đi kèm; tự tạo khi áp dụng.

### Case 1 — typical
```json
{
  "id": "commit-feature",
  "kind": "typical",
  "prompt": "Write a commit message for my staged changes: I added a --json flag to the export command.",
  "should_trigger": true,
  "fixtures": ["fixtures/staged-feature.diff"],
  "expected_behaviors": [
    "Reads the staged diff before writing the message",
    "Uses type feat and a subject of at most 72 characters",
    "Explains why the flag was added in the body, not only what changed"
  ]
}
```

### Case 2 — edge
```json
{
  "id": "commit-breaking-change",
  "kind": "edge",
  "prompt": "Commit my staged changes. The diff renames the --out flag to --output and removes the old name.",
  "should_trigger": true,
  "fixtures": ["fixtures/staged-rename-flag.diff"],
  "expected_behaviors": [
    "Marks the change as breaking with a BREAKING CHANGE footer or a ! after the type",
    "Does not invent a ticket code",
    "Keeps the subject at most 72 characters"
  ]
}
```

### Case 3 — near-miss
```json
{
  "id": "commit-near-miss-changelog",
  "kind": "near-miss",
  "prompt": "Write the changelog entry for version 2.3.0 from the pull requests merged since the last tag.",
  "should_trigger": false,
  "fixtures": [],
  "expected_behaviors": [
    "Writes the changelog entry without producing a Conventional Commits message"
  ]
}
```

## Agentskills export

Bản xuất qua `evals … --export agentskills` (TK8) ghi `<out>/<skill>/evals/evals.json`. Case `should_trigger: false` bị loại (ở đây còn 2 eval, 1 case bị loại). `id` là số nguyên từ 1; `expected_output` nối các `expected_behaviors` bằng "; "; `files` trỏ vào `evals/files/`. Ví dụ viết tay theo schema ở [agentskills.io](https://agentskills.io/skill-creation/evaluating-skills):

```json
{
  "skill_name": "writing-commit-messages",
  "evals": [
    {
      "id": 1,
      "prompt": "Write a commit message for my staged changes: I added a --json flag to the export command.",
      "expected_output": "Reads the staged diff before writing the message; Uses type feat and a subject of at most 72 characters; Explains why the flag was added in the body, not only what changed",
      "files": ["evals/files/staged-feature.diff"],
      "assertions": [
        "Reads the staged diff before writing the message",
        "Uses type feat and a subject of at most 72 characters",
        "Explains why the flag was added in the body, not only what changed"
      ]
    },
    {
      "id": 2,
      "prompt": "Commit my staged changes. The diff renames the --out flag to --output and removes the old name.",
      "expected_output": "Marks the change as breaking with a BREAKING CHANGE footer or a ! after the type; Does not invent a ticket code; Keeps the subject at most 72 characters",
      "files": ["evals/files/staged-rename-flag.diff"],
      "assertions": [
        "Marks the change as breaking with a BREAKING CHANGE footer or a ! after the type",
        "Does not invent a ticket code",
        "Keeps the subject at most 72 characters"
      ]
    }
  ]
}
```
