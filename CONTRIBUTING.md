# Contributing

Keep the central contract intact: source databases open read-only, SQL runs on disposable copies, scenarios reset independently, and reports omit application values. A passing example does not establish behavior for other workloads.

Use Python 3.11 or later and standard-library tests:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
```

For a packaging change, build a wheel, install it into a separate virtual environment, and run `tests/installed_smoke.py` with that environment's Python. The smoke runs outside the source checkout. CI repeats tests and installed-package checks on Python 3.11 and 3.14.

Describe the user-visible behavior, a reproducing synthetic fixture, affected constraints and checks in a pull request. Do not include private databases, credentials, or unsanitized application records. Document new SQLite restrictions and report metadata. Preserve existing outputs and exact expected constraint checks when simplifying code.
