---
name: git-commit
description: Use when committing changes. Triggers on commit, git, changelog. Guides small, well-scoped commits with clear messages.
---

# Git Commit Discipline

When committing:
1. Run `git status` and `git diff` to review exactly what changed.
2. Stage only the files relevant to this unit of work.
3. Write a message: a concise imperative subject (<=72 chars), then a body
   explaining *why* if not obvious.
4. Never commit secrets, credentials, or large binaries.
5. In a dirty repo, commit only your own changes; do not sweep unrelated edits.

Format:
```
<type>: <subject>

<why + what, if needed>
```
where type is one of feat, fix, refactor, docs, test, chore.
