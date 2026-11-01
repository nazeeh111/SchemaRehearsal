# Recorded search reports

These static reports come from the original synthetic FTS5 quickstart at source
revision `c303e9b4d00e5fa274ebd1a2f7eb811d2cb005d7`, using Python 3.14 and
SQLite 3.50.4:

```sh
python3 examples/quickstart.py --fts5 /tmp/new-search-demo
```

The quickstart verifies the broken, repaired and unchanged controls and checks
that its generated source database bytes are preserved. `docs/search-example.html`
is the unchanged broken report; this directory adds its JSON and both control
reports. Reports retain their input hashes and SQLite version. Reproduction
under a different SQLite version can change engine metadata.

The Pages workflow stages only these HTML/JSON files, the existing broken HTML
and an empty `.nojekyll` marker. It never publishes the generated database.
Runtime code, the report renderer and the release package are unchanged.
