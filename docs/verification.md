# Verification

Local evidence from September 27, 2026, macOS arm64, Python 3.14.7 with SQLite 3.50.4:

- 26 standard-library unittest tests passed, covering the application example, main-file/WAL preservation in controlled fixtures, committed WAL capture, independent scenario resets, exact expected constraint outcomes, type/order/duplicate comparisons, source errors, invalid suites, privacy, HTML escaping, output preservation and execution/size/result limits.
- Foreign database attachment, VACUUM INTO, extension loading, dangerous pragmas, virtual tables and explicit TEMP objects were rejected in disposable fixtures.
- Independent review reproduced two resource-bound gaps: TEMP table growth bypassed the main database quota, and quoted semicolons caused repeated statement-prefix scans. Explicit TEMP objects are now rejected, and a quote/comment-aware scan checks its execution deadline. Reviewer re-ran the counterexamples successfully. Malformed expected-error values now produce controlled validation errors.
- Source compilation passed. A source-distribution/wheel build using existing offline cached tooling passed. The exact wheel was installed with --no-index --no-deps in an isolated environment. Its CLI ran from a separate temporary directory and imported from site-packages: broken migration exited 1, repaired and unchanged migrations exited 0. Do not infer remote CI success from this local check.
- `docs/example.html` is generated from the actual synthetic broken-migration result. Both database checks pass, while the audit observation changes from 17 rows to zero. The renderer is static and contains no external resources or application values.

The configured Linux Python 3.11/3.14 CI has not been observed in this unpublished checkout. Local testing does not establish production workload coverage, arbitrary database-engine compatibility, malicious-input containment, a hard total memory bound or directory-wide immutability. Source connections are read-only, but SQLite coordination sidecars and concurrent writers are outside the directory-byte guarantee.
