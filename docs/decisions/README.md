# Architecture Decision Records

Owned by `architect`. One file per decision: `NNNN-short-title.md`, copied from
[0000-template.md](0000-template.md). ADRs are never edited after acceptance — a new ADR supersedes an old one.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-supabase-receiver-laptop-worker.md) | Supabase receiver + laptop worker, with the database as the queue | accepted |
| [0002](0002-staged-cascade-with-jev.md) | Staged analysis cascade with Jev decisions behind protocols | accepted |
| [0003](0003-git-workflow-and-environments.md) | Git workflow, environments and backward-compatible migrations | accepted; #2 superseded by 0005 |
| [0004](0004-local-api-network-boundary.md) | Local API: loopback bind, Host/Origin allowlists, CSRF header, server-checked sessions | accepted; #7 superseded by 0006 |
| [0005](0005-merge-methods-with-back-merges.md) | Merge methods: back-merges into `dev`, squash hotfixes into `main` | accepted |
| [0006](0006-dev-proxy-preserves-host-origin.md) | Dev proxy keeps the browser's Host and Origin; `API_DEV_ORIGIN` matched exactly | accepted |

Superseding only changes the old ADR's status line; its text is never edited.
