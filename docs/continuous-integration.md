# Check a SQLite migration in CI

Use SchemaRehearsal as a check before a deployment. Keep a small synthetic
database, a migration SQL file and a behavior suite in your application repository.
The suite should exercise your application's important writes and observations.
Start with the [audit example](../README.md#try-it-without-installing), then replace
its synthetic scenarios with your own.

Install a reviewed SchemaRehearsal wheel in your CI environment, or check out a
reviewed source revision and install it. The release wheel has no runtime
dependencies. Record the exact artifact and its hash with your build inputs.
The commands below assume the installed `schema-rehearsal` command is available.

## Fail on a changed behavior

```sh
schema-rehearsal check \
  --database ci/fixture.sqlite \
  --migration migrations/next.sql \
  --suite ci/behaviors.json \
  --output rehearsal-report
```

Run this command as its own CI step. Exit 0 means the declared behaviors matched.
Exit 1 means a behavior changed; exit 2 means the check could not finish; exit 3
means the baseline was invalid. All three nonzero exits should fail the gate.
Do not append `|| true` or enable a runner's continue-on-error option. A successful
CI step cannot establish behavior that the suite does not examine.

`rehearsal-report` must not exist. A clean job workspace gives each run its own
destination. If your runner reuses workspaces, choose a fresh destination rather
than deleting a previous report.

## Check each committed migration

When shipping several files, list them explicitly in the order your deployment
will apply them. Do not rely on a shell wildcard to determine their order.

```sh
schema-rehearsal sequence \
  --database ci/fixture.sqlite --suite ci/behaviors.json \
  --migration migrations/001.sql \
  --migration migrations/002.sql \
  --migration migrations/003.sql \
  --output rehearsal-sequence
```

Each checkpoint compares with the same starting snapshot. An intermediate change
keeps exit 1 even if a later migration repairs it. Each migration must finish its
transaction. The same suite must be valid against the starting schema and every
checkpoint. At most eight migrations are supported. Add `--allow-fts5` when your
fixture uses SQLite's built-in FTS5 search.

## Keep the report when a check fails

Configure your runner's artifact step to run after a failed gate as well as a
successful one. Collect `report.html` and `report.json` only if they exist; an input
error can happen before output is created. Keep the original command's exit code
as the gate's result.

Reports omit SQL, parameters and raw result cells, but retain scenario, observation
and schema names, row counts and hashes. Use synthetic fixtures and review the
report before choosing artifact visibility and retention. Database fixtures and
the whole workspace are unnecessary report artifacts.

## Reproduce the setup locally

From the SchemaRehearsal source checkout, this creates only synthetic inputs and
checks the expected broken/repaired/unchanged results:

```sh
python3 examples/quickstart.py rehearsal-demo
```

The **demo wrapper** returns 0 when it reproduces command exits 1, 0 and 0. It
does not accept an application database and is not a production migration gate.
Use `schema-rehearsal check` or `sequence` for the actual CI check.
