# Rehearse statements that must commit together

A deferred foreign key checks a relationship when the transaction commits. An
application can insert a child first, insert its parent second, and commit both.
Autocommit, which commits each statement separately, rejects the first insert.

With SchemaRehearsal 0.2.0 installed, run the synthetic recipe from this checkout:

```sh
python examples/transactions.py transaction-demo
```

The directory must be new and its parent must exist. The recipe uses the real CLI,
checks its reports and exit codes, and verifies the synthetic source bytes stay
unchanged. It creates four results:

| Report directory | Expected result | Evidence |
| --- | --- | --- |
| `deferred` | `matched`, exit 0 | Child then parent commits; a second scenario expects a missing-parent commit failure and observes no pending child. |
| `immediate` | `changed`, exit 1 | Migration makes the foreign key immediate; the child insert fails at the step. |
| `autocommit` | `invalid_baseline`, exit 3 | Omitting transaction mode retains individual statement commits. |
| `unexpected_commit` | `invalid_baseline`, exit 3 | Missing parent fails at commit without a declared expectation. |

Open `transaction-demo/deferred/report.html`, or examine the generated suites to
adapt the workload. A transactional scenario adds one field:

```json
{
  "name": "Child before parent",
  "transaction": "commit",
  "steps": [
    {"sql": "INSERT INTO children VALUES(?,?)", "parameters": [1, 9]},
    {"sql": "INSERT INTO parents VALUES(?)", "parameters": [9]}
  ],
  "observations": [{"name": "Linked children", "sql": "SELECT id FROM children ORDER BY id"}]
}
```

The engine starts and commits one transaction on each disposable scenario copy.
Observations run after it settles. Commit success is expected by default; add
`"expect_commit_error": "SQLITE_CONSTRAINT_FOREIGNKEY"` to expect that exact
constraint code. This expectation is legal only with `"transaction": "commit"`.
A failed commit rolls back all pending changes before observations. Step
expectations retain their existing meaning and do not replace the commit
expectation.

SQLite can end the whole transaction itself, for example with `INSERT OR
ROLLBACK` or a trigger using `RAISE(ROLLBACK, ...)`. Remaining steps are recorded
as `not_run`; commit is `not_attempted`. Such a baseline is invalid even when the
constraint on the failing step was expected. The same behavior introduced by a
migration is a change. Later steps never continue in accidental autocommit mode.

The mode supports one transaction per scenario. User-supplied `BEGIN`, `COMMIT`,
`ROLLBACK` and savepoints remain blocked in steps and observations. Reports show
step and commit codes and result shapes, while retaining the existing SQL,
parameter and result-cell privacy rules.
