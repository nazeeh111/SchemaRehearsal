# Write an observation that catches the right change

Suppose a receipt has three line items: **A, A, B**, each with quantity 1. The
application permits repeated items, and their display order is irrelevant.
Two transformations illustrate the contract:

| Transformation | Items afterward | Count | Distinct items | Required result |
| --- | --- | --- | --- | --- |
| Rebuild the table in a different order | B, A, A | 3 | A, B | Match |
| Accidentally replace one A with B | A, B, B | 3 | A, B | Change |

A row count misses the second change. A set of distinct items also misses it.
An ordered comparison rejects the harmless first change. A **multiset**, a
collection that ignores order but counts repetitions, distinguishes both.

## Run both cases

Install the release as described in the [README](../README.md), then run the
recipe from a source checkout with that environment's Python. It creates only
synthetic data and requires a new output directory:

```sh
python examples/duplicate_rows.py receipt-demo
```

The script invokes the installed CLI from the generated output directory. It checks that
the reordered case exits 0, the changed case exits 1, database checks pass, and
the count observation matches in both cases. Open
`receipt-demo/duplicate_changed/report.html`. The item observation has three
rows and two columns on both sides, but reports a change. Result shape alone
does not establish equality; the engine compares the private cell values too.

Inspect `receipt-demo/suite.json` alongside the two SQL files. The important
observation is:

```json
{
  "name": "Items including duplicates",
  "sql": "SELECT sku,quantity FROM line_items ORDER BY id",
  "order": "multiset"
}
```

The explicit SQL ordering makes the example's order change reproducible; the
multiset comparator deliberately ignores it. Each row includes both SKU and
quantity. Omitting quantity would leave quantity changes untested. Omitting the
generated row ID is intentional here: this receipt contract does not depend on
it. An application with references to those IDs needs a separate observation
covering them. Select fields according to actual application requirements.

## Follow the mechanism

[`rehearse`](../src/schema_rehearsal/engine.py) snapshots the selected database
with SQLite's backup API, then applies each migration to a copy. For each
scenario it makes fresh baseline and migrated copies. `_scenario` runs the
declared steps and observations, and `_cell` preserves each value's SQLite
type. `_rows` bounds returned data. Ordered observations compare row sequences;
multiset observations compare `Counter` objects, which retain multiplicities.

The report stores equality and shapes, not the original cells. This trades
immediate value-by-value diagnosis for reports that expose less application
data. Names and counts remain visible. Use your retained private inputs to
investigate; hashes do not anonymize those inputs.

## Extend the workload

Add a scenario that updates one line's quantity, then observes the receipt's
items and total. Steps run before observations, and every scenario starts from
the same initial snapshot. Bind customer-provided values with `parameters`;
declare an exact `expect_error` for a constraint rejection you depend on.
Choose `ordered` when sequence is part of the contract and use a deterministic
`ORDER BY`. Choose `multiset` only when order is irrelevant.

The [audit-trigger example](../README.md#try-a-migration-that-loses-an-audit-trail)
adds mutation side effects and expected constraint failures. Neither example
models concurrency, performance, every possible input, or production migration
deployment. A match proves only that these declared observations agree on
these snapshots.
