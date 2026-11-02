# A table rebuild that deletes child rows

An actual Drizzle migration can finish without an error, pass SQLite's integrity
and foreign-key checks, and still delete child rows. This example compares that
generated migration with its corrected and unchanged controls.

The case follows [kholdrex's report #6621](https://github.com/drizzle-team/drizzle-orm/issues/6621),
filed November 2, 2026 and closed as a duplicate of [#5469](https://github.com/drizzle-team/drizzle-orm/issues/5469).
The report already identifies the cause and the release-candidate fix. This
example adds an independently regenerated, repeatable behavior comparison.

## Run the comparison

From this Keepstep checkout, use Python 3.11+:

```sh
python3 examples/drizzle-table-rebuild/run.py drizzle-demo
```

No npm, package installation, account or database server is needed. Choose a new
output directory with an existing parent. The wrapper returns 0 only when these
expected results are reproduced:

```text
old       exit 1  child rows 3 -> 0
fixed     exit 0  child rows 3 -> 3
unchanged exit 0  child rows 3 -> 3
All three runs passed integrity and foreign-key checks.
Source database and case input bytes unchanged.
```

Open `drizzle-demo/old/report.html`, then `fixed/report.html`. The declared
queries compare exact child identities and parent links. They also check two
parent rows and one unrelated row as controls. The comparison deliberately
ignores the changed defaults. `summary.json` records the direct local row
results, SQLite version and input hashes; those values are fictional fixture
data. Normal Keepstep reports still omit result cells.

## Where the SQL comes from

The reporter changes the defaults on two independent tables from `a` to `b`.
Rebuilding the first table re-enables foreign keys. The old migration then drops
the parent table while enforcement is on, so `ON DELETE CASCADE` removes its
children. The corrected migration disables enforcement around each rebuild.

| File | Generated with |
| --- | --- |
| `initial.sql`, `old.sql` | drizzle-kit 0.31.11 / drizzle-orm 0.45.4 |
| `fixed.sql` | drizzle-kit 1.0.0-rc.5 / drizzle-orm 1.0.0-rc.5 |
| `unchanged.sql` | No-change control |

`old.sql` matches the SQL in the report except for one final newline. These are
actual generated files, not hand-edited repairs. All three cases use the same
initial database and the reporter's three fictional child rows.

To regenerate, copy [`regenerate`](regenerate/) into a new temporary directory.
It retains the original schema/config and both package lockfiles. For each of
`old` and `rc`, copy `schema.ts` and `drizzle.config.ts` into that folder, run
`npm ci`, then `npx --no-install drizzle-kit generate --name init`. Change only
the two `.default("a")` values in `schema.ts` to `.default("b")`, then run
`npx --no-install drizzle-kit generate --name change_defaults`. Regeneration
requires Node and a one-time public-package download; running this example does
not. The retained generation used Node 24.14.0.

## Scope of the result

The recorded comparison used Keepstep 0.4.0's engine from
[`ec5fb93152744216781e65da13a68850a05ba72e`](https://github.com/nazeeh111/SchemaRehearsal/tree/ec5fb93152744216781e65da13a68850a05ba72e),
Python 3.14.7 and SQLite 3.50.4. This example is included with a compatible
checkout and checked in CI.

This applies the generated SQL directly to disposable local SQLite databases,
outside an outer transaction. It does not run Cloudflare D1, better-sqlite3,
Drizzle's migration runner, deployed applications or concurrent writers. It does
not establish that all migrations are safe or recommend upgrading to a release
candidate. Source and input preservation here concerns the generated fixture,
not an arbitrary live application's directory.
