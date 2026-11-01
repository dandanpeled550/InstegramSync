# As which Postgres role does the Supabase CLI run migrations, and what does that mean for default privileges?
- Answer: Remote `db push` with login (no DB password) connects as the temp role `cli_login_postgres`, then runs `SET SESSION ROLE postgres`, so `current_user = 'postgres'` while `session_user = 'cli_login_postgres'`. With a DB password / `--db-url` as `postgres` (direct or pooler) both are `postgres`. Locally the CLI connects as `postgres`. So a guard on `current_user = 'postgres'` passes in all CLI cases, provided the CLI is new enough to have the step-down (present in v2.90.0; absent in v2.40.0). Do not guard on `session_user`. The GitHub integration's role is undocumented.
- Confidence: high for CLI v2.122.0 source behaviour (read directly); medium for local stack; low for GitHub integration / branching.
- Checked: 2026-11-01
- Sources: Supabase CLI source (`supabase/cli`) at tag v2.122.0 (`5afad870388552d0198087d27037da7ac745ba2b`) and v2.90.0; Supabase docs/KB; PostgreSQL docs (links below).

## Details

### Per case

| # | Case | `session_user` | `current_user` | Object owner | Confidence |
|---|---|---|---|---|---|
| 1 | `supabase start` / `db reset` (local Docker) | `postgres` | `postgres` | `postgres` | medium |
| 2a | `db push --linked` after `supabase login` + `link`, no DB password | `cli_login_postgres` (temp role minted via Management API) | `postgres` (after `SET SESSION ROLE postgres`) | `postgres` | high |
| 2b | `db push` with `SUPABASE_DB_PASSWORD` / `-p` (linked), or `--db-url` as `postgres` — direct host | `postgres` | `postgres` | `postgres` | high |
| 2c | Same as 2b through the pooler (`postgres.<ref>` user, Supavisor, port 5432 session mode) | `postgres` | `postgres` | `postgres` | high (user name) / medium (pooler maps it to `postgres`; standard Supavisor behaviour) |
| 3 | GitHub integration / branching | not documented | not documented | not documented | low |

### Evidence

1. Step-down rule (CLI source). `apps/cli/src/command-internal/db-connection.sql-pg.layer.ts` @ v2.122.0 defines `SET_SESSION_ROLE = "SET SESSION ROLE postgres"` and `needsRoleStepDown(user)`: true if the user (after stripping a `.<ref>` Supavisor suffix) is `supabase_admin` or starts with `cli_login_`. It applies only to remote targets. The comment says the step-down exists so "`CREATE EXTENSION` execute as `postgres` rather than the temp role". The older Go implementation does the same: `internal/utils/connect.go` @ v2.90.0 (`ConnectByConfigStream`, `AfterConnect` runs `SET SESSION ROLE postgres` for `supabase_admin` or `cli_login_*`). The same file @ v2.40.0 has no step-down, so very old CLIs would run as `cli_login_postgres` (exact introducing version not determined).
2. The step-down is re-asserted after role reverts. Commit `0c721790` (2026-08-18, "restore postgres after role reverts (CLI-2205)", supabase/cli#6246) re-applies `SET SESSION ROLE postgres` after any top-level `RESET ROLE` / `SET ROLE NONE` / `DISCARD ALL`, at the end of each migration file, and before the history insert, so `current_user` matches the password path "for the whole file". Residual gaps (dynamic SQL, `SET LOCAL ROLE NONE`) exist. `RESET ALL` does not revert the role (`role` is `GUC_NO_RESET_ALL`, per source comment). Related fix `b08e6e1f` (2026-07-21, #5895) re-runs the step-down on every new physical connection.
3. Local default user. Go `ConnectLocalPostgres` @ v2.90.0 defaults `config.User` to `postgres` (db `postgres`, port from `[db].port`, default 54322) and no step-down applies to local targets. I did not read the TS local reset path end to end; PR #5895 text notes pg-delta introspection (not migration apply) connects locally as `supabase_admin`, which is a different code path. Treat migration apply locally as `postgres` (medium).
4. Temp role. Supabase KB: `cli_login_postgres` is "a temporary role automatically created by the Supabase CLI" for admin tasks when no DB password is supplied; supplying `SUPABASE_DB_PASSWORD` makes the CLI authenticate as `postgres` directly (KB: "Permission denied when deleting the cli_login_postgres role").
5. Transactionality. `db push` SIDE_EFFECTS (v2.122.0, `apps/cli/src/commands/db/push/SIDE_EFFECTS.md`) and Go `MigrationFile.ExecBatch` (v2.40.0, "ExecBatch is implicitly transactional") show each migration file runs as one implicit transaction together with the `schema_migrations` insert, except `CREATE INDEX CONCURRENTLY`, `VACUUM`, `ALTER SYSTEM`, `CLUSTER`, which run standalone. A `RAISE EXCEPTION` guard at the top therefore aborts and rolls back the whole file.
6. CLI uses session mode for the pooler: Go `GetPoolerConfig` sets `poolerConfig.Port = 5432` ("Supavisor transaction mode does not support prepared statement"), so `SET SESSION ROLE` persists. Do not hand-craft a `--db-url` on port 6543 (transaction mode): session-level state is not guaranteed there (general Supavisor behaviour; unverified for this CLI).

### Default privileges and ownership

- `ALTER DEFAULT PRIVILEGES` without `FOR ROLE` applies to the current role (`current_user`), only to objects created later by that role, never to existing objects (PostgreSQL docs, `sql-alterdefaultprivileges`). Because of the step-down, `current_user` is `postgres` in cases 2a/2b, so the defaults are registered for `postgres`. Write `FOR ROLE postgres` explicitly anyway.
- Defaults are per creating role. Supabase KB ("Can't change the default privileges of supabase_admin in the public schema"): two roles have default privileges in `public`, `postgres` and `supabase_admin`; the `supabase_admin` ones grant `anon`/`authenticated`/`service_role` access to objects `supabase_admin` creates there (mainly extensions installed in `public`). `postgres` can alter only its own defaults and cannot change `supabase_admin`'s. So revokes issued as `postgres` do not apply to future objects created by `supabase_admin` (high, official KB). Keep extensions out of `public` and the revoke covers everything the migrations create. A community thread (labeled community, GitHub Discussions #47183 / #48259) reports the same and that Supabase had not published a supported way to alter the `supabase_admin` ACLs.
- Ownership: objects created by migrations are owned by `postgres` in all CLI cases (case 2a thanks to the step-down; `CREATE` after `SET SESSION ROLE` uses `current_user`).

### Extensions

- Supabase docs (database/extensions): most extensions are installed in the `extensions` schema, and the SQL example uses `create extension ... with schema extensions`. A bare `CREATE EXTENSION` is not documented to default to `extensions`; where it lands depends on `search_path` and the extension (non-relocatable ones fix their own schema, e.g. `pg_cron` in `pg_catalog`, `pg_net` in `net`, `supabase_vault` in `vault` - from memory of Supabase behaviour, unverified here). Always write `create extension if not exists <name> with schema extensions;` where the extension is relocatable. Note: as `postgres` (not superuser) only trusted/allowed extensions can be created; this works on hosted and local images.

### Recommended guard

The existing form is correct for the CLI as long as the CLI version includes the step-down:

```sql
do $$
begin
  if current_user <> 'postgres' then
    raise exception 'migration must run as postgres, got current_user=% (session_user=%)',
      current_user, session_user;
  end if;
end $$;
```

- Check `current_user`, not `session_user` (`session_user` is `cli_login_postgres` in case 2a and that is fine).
- Do not use `pg_has_role(current_user, 'postgres', 'member')`: it also passes for an un-stepped-down `cli_login_postgres`, which would then own the objects and make default privileges apply to the wrong role. That defeats the guard's purpose.
- Do not add `SET ROLE postgres` inside the migration to "fix" it: harmless when stepped down, but it hides a misconfigured CLI and `cli_login_postgres` may not be allowed to `SET ROLE` in all setups (unverified).
- Pin a minimum CLI version in CI (>= v2.90.0; the repo can simply use latest) so an old CLI cannot silently run as `cli_login_postgres`; the guard then fails loudly instead.
- If CI deploys via `SUPABASE_DB_PASSWORD` (recommended for non-interactive CI, avoids the temp role), the connection is plain `postgres` and the guard is trivially true.
- Avoid `RESET ROLE` / `SET ROLE` in migrations; if used, the CLI restores `postgres` (v2.122.0), but older CLIs do not.

## Open questions
- Unverified: GitHub integration / branching role. Docs (branching/github-integration) say migrations run on branch create and on each commit, one transaction per file, and do not name a role. If staging ever uses the integration instead of CI `db push`, test the guard on a throwaway branch first.
- Unverified: exact CLI version that introduced the step-down (somewhere between v2.40.0 and v2.90.0).
- Unverified: whether the TS local `db reset` path connects as `postgres` for migrations (Go path does; TS path not fully read), and whether local `postgres` is a true superuser (hosted `postgres` is not).
- Unverified: where a bare `CREATE EXTENSION` lands for the `postgres` role's `search_path`.
- Unverified: whether Supabase ever creates objects in `public` as `supabase_admin` on a customer project (no official answer found).

## Sources
- Supabase CLI @ v2.122.0 (`5afad870388552d0198087d27037da7ac745ba2b`): `apps/cli/src/command-internal/db-connection.sql-pg.layer.ts`, `apps/cli/src/command-internal/migration-apply.ts`, `apps/cli/src/command-internal/db-connection.service.ts`, `apps/cli/src/commands/db/push/SIDE_EFFECTS.md` - https://github.com/supabase/cli
- Supabase CLI @ v2.90.0 `internal/utils/connect.go`; @ v2.40.0 `internal/utils/connect.go`, `pkg/migration/file.go`
- supabase/cli commits `0c721790` (#6246) and `b08e6e1f` (#5895)
- Supabase KB, cli_login_postgres: https://supabase.com/kb/troubleshooting/permission-denied-when-deleting-the-cli_login_postgres-role
- Supabase KB, supabase_admin default privileges: https://supabase.com/kb/troubleshooting/cant-change-the-default-privileges-of-supabase_admin-in-the-public-schema
- Supabase docs, extensions: https://supabase.com/docs/guides/database/extensions
- Supabase docs, branching GitHub integration: https://supabase.com/docs/guides/deployment/branching/github-integration
- PostgreSQL docs, ALTER DEFAULT PRIVILEGES: https://www.postgresql.org/docs/current/sql-alterdefaultprivileges.html
- Community (labeled): https://github.com/orgs/supabase/discussions/47183 , https://github.com/orgs/supabase/discussions/48259
