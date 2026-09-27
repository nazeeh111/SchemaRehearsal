# SchemaRehearsal

**Find application behavior changes that a successful SQLite migration can hide.**

A table rebuild can preserve every row and pass database integrity checks while dropping the trigger that records payments. SchemaRehearsal runs your declared workloads on independent before/after copies and reports what changed. It never applies a migration to your selected source database.

Python 3.11 or later. No runtime dependencies, account, network connection, or database server. The [release](https://github.com/nazeeh111/SchemaRehearsal/releases/latest) includes a wheel for offline installation with `python -m pip install --no-index --no-deps schema_rehearsal-0.1.0-py3-none-any.whl`. Or install from this source checkout:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install .
schema-rehearsal --version
```

## Try a migration that loses an audit trail

```sh
schema-rehearsal example example
schema-rehearsal check --database example/orders.sqlite \
  --migration example/broken.sql --suite example/suite.json --output broken-report
# Exit 1: the payment workflow changes.

schema-rehearsal check --database example/orders.sqlite \
  --migration example/repaired.sql --suite example/suite.json --output repaired-report
# Exit 0: declared behaviors match.
```

Open `broken-report/report.html` in your browser, or read `report.json` in CI. Every output directory must be new; existing files are never replaced. The example command also requires a new directory, with an existing parent. An error can leave a partial new directory for inspection; choose a new path for a retry.

The original synthetic fixture has 20 accounts and 200 orders. Both migrations keep those rows and pass integrity and foreign-key checks. Paying 17 orders produces 17 audit records before migration, **zero** after the broken migration, and 17 after the repaired one. A second scenario checks an exact constraint failure; a third demonstrates that scenarios start independently. No production database is included.

## Describe the behavior you depend on

A suite is a JSON file. Each named scenario has mutation `steps`, followed by read-only `observations`:

```json
{
  "format": "schema-rehearsal/v1",
  "scenarios": [{
    "name": "Pay an order",
    "steps": [{
      "sql": "UPDATE orders SET status=? WHERE id=?",
      "parameters": ["paid", 1]
    }],
    "observations": [{
      "name": "Audit coverage",
      "sql": "SELECT order_id, new_status FROM audit ORDER BY order_id",
      "order": "ordered"
    }]
  }]
}
```

Each step is one SQL statement; triggers run normally. Bound parameters support null, strings, signed 64-bit integers and finite real numbers. A step can declare `"expect_error": "SQLITE_CONSTRAINT_CHECK"` or another exact SQLite constraint code. If the baseline does not meet that expectation, the baseline is invalid. A different constraint outcome after migration is a behavior change. Other SQLite execution failures are errors, with their raw messages withheld.

Observations compare SQLite value types and values. Integer `1`, real `1.0`, text `"1"`, null and a BLOB are distinct. `ordered` is the default: provide an `ORDER BY` that makes your intended order deterministic. `multiset` ignores row order but preserves duplicate multiplicity. Column count is compared; result-column labels are not. Step result rows are consumed and bounded, but only their success/constraint outcomes are compared; use observations for values you want checked.

The migration file supports multiple statements, quoted semicolons, trigger bodies and explicit transactions. It must finish with no open transaction. Scenario steps run in autocommit mode and cannot control transactions or modify schema. Observations cannot mutate the database. Every scenario starts from fresh copies, not the preceding scenario's result.

## What the result means

| Exit | Status | Meaning |
| --- | --- | --- |
| 0 | `matched` | All declared behaviors match. |
| 1 | `changed` | At least one step outcome or observation changed. |
| 2 | `error` | Invalid input, unsupported operation, migration failure, limit, or other execution/output error. |
| 3 | `invalid_baseline` | Baseline database checks or a baseline scenario failed. |

Reports keep the engine version, input hashes, copied-snapshot hash, database checks, schema-object changes, scenario outcomes and result shapes. They omit SQL, parameters, raw result cells, database paths, snapshots and raw SQLite errors. **Scenario names, observation names, schema names and row counts remain visible metadata.** Do not put secrets in those names. Hashes are evidence of equality, not anonymization. Retain inputs privately to reproduce a result.

A changed scalar observation can show one row before and after: its hidden cell changed, not its shape. To investigate, find the named observation in your private suite and reproduce its steps and query on your own disposable before/after copies. The report deliberately does not disclose those values.

This tool tests declared behaviors, not all possible application behavior. It does not generate or apply production migrations, certify migration safety, measure production performance, or model concurrent application writers.

## Boundaries

The source opens with SQLite `mode=ro`. SQLite's backup API captures committed WAL data into a private in-memory snapshot; simply copying the main database file would miss it. SQL writes run only on copies. SQLite may create or update coordination sidecars such as `-shm`, and another writer may change the source concurrently. We do not promise that the whole source directory stays byte-for-byte identical. Use a selected database you are permitted to read, and retain your normal backups.

Default limits: 64 MiB per database copy and source sidecar, 1 MiB per input file, 32 scenarios, 64 steps and 16 observations per scenario, 10,000 rows and 2 MiB encoded result data per statement, and a 30-second cooperative execution deadline. Result bounds apply to migration and step results too. Copies coexist, so these are workload bounds, not a hard total process-memory or operating-system sandbox. A single SQLite call or OS operation can delay cooperative interruption.

External attachment, extension loading, virtual tables, explicit TEMP objects, file-writing SQL, unsafe pragmas and common time/random functions are blocked. Migrations may set only `foreign_keys`, `defer_foreign_keys` and `user_version`; selected metadata pragmas are readable. Foreign-key enforcement and recursive triggers are enabled for scenarios. Custom collations/functions, encrypted databases and virtual-table databases are unsupported. A workload requiring blocked date/time functions needs fixed values supplied as parameters. See [design and tradeoffs](docs/design.md).

## Development

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
```

CI is configured to run tests on Linux with Python 3.11 and 3.14, build a wheel and run the installed CLI outside the source tree. See [verification](docs/verification.md) for actual recorded results and remaining limits.

Original software under the [MIT license](LICENSE). Migration testing is an established technique; this project focuses on a small, local SQLite workflow and explicit behavioral evidence.
