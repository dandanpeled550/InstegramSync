## What & why
<!-- 2–4 sentences. What changes, and why it's needed. -->

## Task
<!-- Link: docs/tasks/M<n>.md#<task-id> -->

## Contracts touched
<!-- none | docs/contracts/<file> + ADR link -->

## How it was tested
<!-- Commands run and their results. Screenshots for UI changes. -->

## Risk & rollback
<!-- What could break, how to revert. Migration notes (must be backward-compatible). -->

## Checklist
- [ ] Gate checks green locally
- [ ] Tests cover the new behavior (no network in unit tests)
- [ ] No secrets, personal data, or real Instagram content
- [ ] Contracts unchanged, or ADR linked
- [ ] Migrations backward-compatible (expand → migrate → contract)
- [ ] Conventional Commit title, labels set (`M<n>`, `area:<scope>`, `agent:<name>`, `security` if needed)
