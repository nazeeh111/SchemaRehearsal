# Design and tradeoffs

The user supplies one ordinary SQLite database, one migration and one deterministic scenario suite. The result shows whether those scenarios behave differently without applying SQL writes to the selected database or exposing its result cells in reports.

## Execution

1. Validate bounded suite input and reserve an exclusive output directory before database execution.
2. Open the database read-only and copy it using SQLite's backup API. Its progress callback bounds pages and time, including busy retries. Ordinary file copying is not used because committed state can reside in a write-ahead log.
3. Run integrity and foreign-key checks on the snapshot, then hash its serialized copied state. The hash is of this normalized snapshot, not the live main file or WAL bytes.
4. Migrate a second copy. A quote/comment-aware scan skips irrelevant semicolons and uses SQLite's `complete_statement` to recognize complete trigger bodies. The scan checks its deadline. Explicit migration transactions are supported and must close. Check migrated integrity and foreign keys; record schema-object differences as context.
5. Make fresh baseline/migrated copies for every scenario. Compare mutation outcomes using exact SQLite constraint codes. Optional `transaction: "commit"` runs steps in one engine-controlled transaction and compares commit outcomes too. Roll back a failed commit before observations. If SQLite ends a transaction implicitly, skip remaining steps and record `not_run` and commit `not_attempted`. Compare observation values as typed tuples, ordered by default or counted as a multiset. Original values exist only in memory during comparison.
6. Write JSON and HTML-escaped static HTML. No snapshots, result cells, bound values, SQL or raw exception messages are written to reports. Schema and user-selected descriptive names are retained.

A schema diff is context rather than a pass/fail gate: a useful migration changes schema. Explicit workloads distinguish intended structural changes from lost side effects. A passing workload does not establish correctness outside that workload.

## Restrictions

The SQLite authorizer denies ATTACH/DETACH, virtual tables, explicit TEMP objects, dangerous pragmas and external file/extension functions. VACUUM INTO requires an attachment and is rejected. Scenario mutations permit DML, not DDL or transaction control; observations permit reads only. Independent copies avoid relying on rollback to erase every possible scenario effect.

Scenario steps default to autocommit mode, so each successful statement commits individually. `transaction: "commit"` starts and commits one transaction with fixed engine SQL outside the user-SQL authorizer. User-supplied transaction control remains denied. Exact `expect_commit_error` constraint expectations are legal only in commit mode. Unexpected baseline step or commit outcomes invalidate the baseline; migrated differences change the result. Cleanup clears deadline handlers before rollback so pending rows cannot reach observations. Nested transactions and savepoints are unsupported.

Foreign keys and recursive triggers are enabled for all scenario connections. A migration can temporarily alter foreign-key behavior, but final checks still run and scenario settings are restored. Applications intentionally using different settings are outside this version's contract. Common time/random functions are denied to reduce misleading comparisons; deterministic ordering and suitable scenarios remain the author's responsibility.

The progress deadline and backup callback bound cooperative execution. Page quotas bound each main database copy; explicit TEMP objects are denied so they cannot bypass that quota. Internal SQLite sorting uses memory. Row and encoded-byte quotas bound returned values. These do not sandbox a malicious SQLite engine or impose a hard total resident-memory ceiling. The CLI executes no Python supplied by users or shell commands and loads no SQLite extensions.

## Privacy and recovery

Raw SQLite messages can contain data, so reports contain diagnostic classes/codes. Names and result shapes may still be sensitive metadata. Hashes are reproducibility evidence, not anonymization.

The selected source opens read-only. SQLite can still touch coordination sidecars, and live writers can change the source; directory byte immutability is not promised. Tests verify main-file/WAL bytes and logical records in controlled fixtures. Output and examples use new directories and exclusive file creation. Failure can leave a partial new report directory for inspection; it never replaces an existing deliverable.

## Primary references

- [SQLite backup API](https://www.sqlite.org/backup.html): WAL-aware snapshots.
- [SQLite table-rebuild procedure](https://www.sqlite.org/lang_altertable.html): reconstructing related objects.
- [SQLite DROP TABLE](https://www.sqlite.org/lang_droptable.html): associated triggers are removed.
- [SQLite pragmas](https://www.sqlite.org/pragma.html): integrity and foreign-key checks are separate.
- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html): backup, authorizer, limits and progress callbacks.
- [Atlas migration tests](https://www.atlasgo.io/testing/migrate): existing work; no novelty claim for the general technique.
