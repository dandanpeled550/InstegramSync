---
name: start-task
description: Start an Insta Saver task the right way — fresh branch from origin/dev with the conventional name, and a draft PR from the template. Use at the beginning of every task.
argument-hint: <task-id> <branch-name>
---

# /start-task $ARGUMENTS

1. `git fetch origin`
2. Create the branch from the latest `dev`: `git switch -c <branch-name> origin/dev`
   - Names: `feat/<milestone>-<area>-<slug>`, `fix/<slug>`, `test/<slug>`, `docs/<slug>`, `chore/<slug>`,
     `refactor/<slug>`.
3. Make your first small commit (Conventional Commit with your area scope, model trailer at the end).
4. `git push -u origin <branch-name>`
5. Open a draft PR into `dev`:
   ```bash
   gh pr create --base dev --draft --title "<type>(<scope>): <summary>" \
     --body-file .github/pull_request_template.md \
     --label "M<n>" --label "area:<scope>" --label "agent:<your-name>"
   ```
   Then edit the body (`gh pr edit <n> --body ...`) to fill every template section and link the task
   (`docs/tasks/M<n>.md#<task-id>`). Add `--label security` for trust-boundary changes.
6. Work in small commits. When your gate passes: `gh pr ready <n>`.
