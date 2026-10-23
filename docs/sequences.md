# A repaired final state can hide an intermediate regression

This example uses synthetic orders and payments. It runs the production CLI,
including the ordinary final-only comparison and the sequence command. No
private database or network service is needed.

After installing SchemaRehearsal, run this script from a source checkout or release
source archive. Choose a new destination whose parent already exists:

```sh
python examples/sequence.py /tmp/schema-sequence-demo
```

Expected output includes:

```text
matched: 3 completed scenarios; report.json and report.html written.
changed: 3/3 checkpoints; first changed checkpoint: 2; final: matched; report.json and report.html written.
```

Open `/tmp/schema-sequence-demo/sequence/report.html`. The report contains real
CLI results. Expand a checkpoint to inspect the workload comparisons.

| Checkpoint | Migration | Audit records after paying 17 orders | Result |
| --- | --- | --- | --- |
| 1 | No-op | 17 | matched |
| 2 | Rebuild orders, forget its audit trigger | 0 | changed |
| 3 | Restore the trigger | 17 | matched |

Every checkpoint passes SQLite integrity and foreign-key checks. The ordinary
check applies all three migrations before running the workloads, so it sees only
the repaired state and returns exit 0. The sequence returns exit 1 because the
middle checkpoint changed a declared behavior. Workload payments run on disposable
copies; they do not accumulate in the migration state or the selected source.

This illustrates why checking the final database alone cannot establish behavior
at an intermediate committed migration. It does not demonstrate a real deployment
failure or model traffic during an upgrade. If your runner applies the whole chain
atomically and no application observes intermediate states, a final-only check may
be sufficient for that particular concern. Sequence boundaries must represent
states you actually care about testing.

## Use with your own migrations

Write a suite for behaviors that should remain stable, then supply files in their
actual application order. The command neither discovers files nor sorts them.
Repeated file arguments are allowed and executed repeatedly.

```sh
schema-rehearsal sequence --database app.sqlite --suite suite.json \
  --migration migrations/001-index.sql \
  --migration migrations/002-rebuild.sql \
  --migration migrations/003-trigger.sql \
  --output rehearsal-2026-10-11
```

Each file must finish outside a transaction. A failure stops execution, and
checkpoints after it have `status: "not_run"` with no nested report. A changed
workload continues to later checkpoints, allowing you to see repairs. The aggregate
exit code remains 1 after repair; execution error 2 and invalid baseline 3 take
precedence. Read `final_status` separately from `status`.

All comparisons use one source snapshot captured with SQLite's backup API,
including committed WAL data. Each checkpoint contains the ordinary report format,
with schema differences and observations compared to that starting snapshot,
not to the preceding checkpoint. An ordered list of per-file SHA-256 hashes binds
the sequence identity. No filenames, SQL, parameters or raw result cells appear in
reports; names, row counts, schema names and hashes remain metadata.

The inherited database/result bounds apply, alongside eight migrations, 1 MiB
combined SQL and one shared cooperative 30-second deadline. The migration state is
cumulative in memory, not a series of repeatedly re-applied prefixes. Runtime grows
with workload size and checkpoint count. A matched result covers declared behaviors
only. It is not proof of compatibility for undeclared operations or changed
application versions, and hashes do not anonymize input data.

## Alternatives and scope

Migration testing is established. [Atlas](https://atlasgo.io/guides/testing/triggers)
tests triggers and schema behavior with a broader migration workflow.
[SQLite's sqldiff](https://sqlite.org/sqldiff.html) compares database contents; it
does not currently display trigger or view differences. SchemaRehearsal focuses on
replaying selected application workloads on copies and showing each checkpoint's
comparison with a fixed starting state. It does not generate or deploy migrations.

SQLite's [table-rebuild guidance](https://sqlite.org/lang_altertable.html#making_other_kinds_of_table_schema_changes)
explicitly requires reconstructing indexes, triggers and views. The deliberately
omitted trigger in this synthetic example follows that known failure mechanism.

## Preserve publication receipts after deleting content

A second [runnable example](../examples/publication_receipts.py) follows a concrete
preservation contract suggested by
[TheodorNEngoy in the Datasette discussion](https://github.com/simonw/datasette/discussions/2997#discussioncomment-18870847):
content can be deleted while its publication receipt remains, so a later retry
with the same account and request ID cannot publish it again. The fixture and SQL
are synthetic. They do not reproduce or validate
Turnfeed's schema, implementation, or deployment.

With SchemaRehearsal installed, choose a new destination with an existing parent:

```sh
python examples/publication_receipts.py /tmp/publication-receipts-demo
```

The fixture publishes a synthetic post, records its receipt, then deletes only
the content. `publication_receipts` uses `(account_id, request_id)` as its primary
key and retains `original_post_id`. It deliberately has no foreign key requiring
the content row to exist. The sequence runs three committed SQL files:

| Checkpoint | Migration | Deleted content rows | Original receipt rows | Result |
| --- | --- | ---: | ---: | --- |
| 1 | Retain a separate recovery copy of the receipts | 0 | 1 | matched |
| 2 | Wrongly prune receipts with no remaining content | 0 | 0 | changed |
| 3 | Restore original receipt keys and payload from the retained copy | 0 | 1 | matched |

The `Deleted post invariant` scenario has no writes. It compares content absence
by both the original post ID and the account/request key, plus the exact receipt
key and original post ID at each checkpoint against the starting snapshot. The receipt observation selects the actual row rather than
only a count, so changing its payload also changes the comparison. As elsewhere,
the tool compares declared observations; it does not infer these requirements.

A separate `Same account delayed retry` scenario uses a small SQL stand-in for an
application's receipt lookup: insert content only when no receipt exists for that
account and request ID. Its content-row results are **0 → 1 → 0**. An independent
account can reuse the request ID at every checkpoint, preventing an accidentally
global request-ID lookup from passing this control. Each scenario starts from its
own disposable copy, so these trial writes never become migration state.

All SQLite integrity and foreign-key checks pass. The ordinary final-only check
returns 0 because all three migrations finish before the scenarios run. The
sequence returns 1, identifies checkpoint 2 as the first change, and reports
`final_status: "matched"`. Open the generated `sequence/report.html` to inspect
the comparisons; its row counts and hashes omit the raw receipt values.

The retained recovery table is explicitly created at checkpoint 1 and used by
checkpoint 3. SchemaRehearsal does not recover a discarded receipt from deleted
content or generate a repair. A real recovery source would need its own retention
and consistency guarantees. This example checks one sequential database contract,
not application retry code, concurrent requests, network delivery, or crash
recovery. Actual application retry behavior needs a corresponding integration
test. If no application observes intermediate committed states, evaluate whether
these particular checkpoints matter to your migration runner.
