# Verification

## Opt-in FTS5 in 0.4.0

Local evidence from October 16, 2026, macOS arm64:

- The 62-test standard-library suite passed on Python 3.14 / SQLite 3.50.4.
  Seven new FTS5 regressions passed on that runtime and bundled Python 3.12 /
  SQLite 3.53.1. A private test spy needed the new keyword forwarded; the first
  failing run was retained before the correction. A subsequent callback binding
  cleanup passed the seven focused cases again. Formatting preserved the Python
  syntax tree; import sorting and an explicit test subprocess option were the
  other cleanup changes. Lint, source compilation and whitespace checks passed.
- A fresh independent reviewer accepted the change with no actionable findings.
  Its 57-case matrix passed on both SQLite versions: cold stored/contentless and
  reduced-index configurations, quoted/multiple tables, exact module refusals,
  migration creation/removal/rename, transactional FTS writes, read-only
  observations, scenario schema/transaction restrictions, unsafe SQL refusals,
  limits, checkpoints, source bytes and JSON/HTML privacy. Two initial reviewer
  expectations were corrected against raw SQLite behavior, with their original
  failed harness receipts preserved. These are finite synthetic checks.
- The production CLI's original synthetic [search recipe](full-text-search.md)
  returned default refusal 2, lost-update-trigger 1, repaired trigger 0,
  tokenizer change 1 and cumulative sequence 1. Checkpoints were
  matched/changed/matched with first change 2. Controlled source bytes were
  preserved; report JSON omitted article values, search terms, SQL and paths.
- The actual generated HTML was inspected at desktop width 1280 and phone width
  390. The document did not overflow horizontally. At phone width, 640-pixel
  tables scrolled within focusable 356-pixel regions; ArrowRight moved the
  focused table and Enter opened reproduction details. The README image is an
  actual report screenshot. This is a bounded manual check, not accessibility
  certification.

The feature uses only built-in FTS5 and explicit opt-in. General database checks
are not an FTS5 index/content consistency check. These results do not establish
universal SQLite compatibility, production performance, all search semantics or
outside adoption. No FTS5-unavailable Python build was present locally; those
feature tests explicitly skip when unavailable. Hosted CI and installed-artifact
results are separate from these local source checks.

## Migration sequences in 0.3.0

Local evidence from October 11, 2026, macOS arm64:

- All 55 standard-library tests passed separately on Python 3.12 and 3.14.
  Sequence cases include a changed middle checkpoint repaired by the final one,
  cumulative data changes, independent workloads, frozen committed WAL capture
  despite a later source writer, transaction-boundary failure, invalid baseline,
  execution stopping, aggregate precedence, ordered input identity, limits,
  source preservation, privacy and escaped HTML diagnostics.
- A fresh independent reviewer reproduced three gaps: loss of an already observed
  change when a later scenario errors, missing migration identity on a preexisting
  single-migration error path, and omitted HTML diagnostic context. All three were
  repaired with focused regression cases. Final review status is recorded with
  the delivery, separately from these test results.
- An offline-built wheel was installed without dependencies in separate clean
  Python 3.12 and 3.14 environments. Existing installed CLI smoke checks passed.
  The installed sequence demo ran outside the source checkout: final-only exit 0;
  sequence exit 1; checkpoints matched/changed/matched, first change 2; controlled
  source database bytes preserved. See [the recipe](sequences.md).
- The actual generated report was operated in the browser at desktop and
  390-pixel width. Document width stayed 390, tables scrolled within focusable
  regions, ArrowRight moved the sequence table by 40 pixels, and Enter opened
  the repaired checkpoint. This is a bounded manual check, not accessibility
  certification or physical-touch testing.
- Source lint, formatting and whitespace checks passed. CI retains Python 3.11
  and 3.14 and now runs the installed sequence recipe. Local results do not imply
  a completed hosted CI run or local Python 3.11 verification.

These are synthetic workflow checks, not evidence of production use or a
concurrent deployment model. Single-migration functionality and its limitations
remain. The [sample report](sequence-example.html) is actual generated output.

## Transaction scenarios in 0.2.0

Local evidence from September 29, 2026, macOS arm64, Python 3.14.7 with SQLite 3.50.4:

- The changed implementation passed the existing 26 tests and ten new transaction
  tests in one 36-test run. A subsequent regression for a migrated commit failure
  passed with all eleven transaction tests. It confirms equal successful step
  outcomes can still produce a changed commit, with pending rows rolled back.
- Coverage includes deferred child-before-parent inserts, deferred-to-immediate
  constraints, exact expected/unexpected commit failures, commit differences in
  both directions, `RAISE(ROLLBACK)` and `INSERT OR ROLLBACK`, continued execution
  after statement-level `ABORT`, skipped steps after transaction rollback,
  interruption cleanup, blocked manual transaction control, bounded read-only
  observations, report escaping and value privacy. Source compilation and
  `git diff --check` passed.
- The 0.2.0 wheel was built offline with the bundled Python 3.12.14,
  setuptools 84.0.0 and wheel 0.48.0. That exact wheel was installed with
  `--no-index --no-deps` in a fresh Python 3.14 environment. The
  [transaction recipe](transactions.md) ran its CLI subprocesses outside the
  source tree with `PYTHONPATH` unset, imported from `site-packages`, and verified
  exits 0/1/3/3 for deferred/immediate/autocommit/unexpected-commit results.
  It also checked the synthetic source bytes stayed unchanged and the failed
  commit's observation contained no pending child.
- CI retains Python 3.11 and 3.14 and now invokes this same recipe with its
  installed wheel. These local results do not establish a hosted CI result or
  local Python 3.11 coverage for 0.2.0.

## Earlier release evidence

Local evidence from September 27, 2026, macOS arm64, Python 3.14.7 with SQLite 3.50.4:

- 26 standard-library unittest tests passed, covering the application example, main-file/WAL preservation in controlled fixtures, committed WAL capture, independent scenario resets, exact expected constraint outcomes, type/order/duplicate comparisons, source errors, invalid suites, privacy, HTML escaping, output preservation and execution/size/result limits.
- Foreign database attachment, VACUUM INTO, extension loading, dangerous pragmas, virtual tables and explicit TEMP objects were rejected in disposable fixtures.
- Independent review reproduced two resource-bound gaps: TEMP table growth bypassed the main database quota, and quoted semicolons caused repeated statement-prefix scans. Explicit TEMP objects are now rejected, and a quote/comment-aware scan checks its execution deadline. Reviewer re-ran the counterexamples successfully. Malformed expected-error values now produce controlled validation errors.
- Source compilation passed. A source-distribution/wheel build using existing offline cached tooling passed. The exact wheel was installed with --no-index --no-deps in an isolated environment. Its CLI ran from a separate temporary directory and imported from site-packages: broken migration exited 1, repaired and unchanged migrations exited 0. Do not infer remote CI success from this local check.
- `docs/example.html` is generated from the actual synthetic broken-migration result. Both database checks pass, while the audit observation changes from 17 rows to zero. The renderer is static and contains no external resources or application values.

[GitHub CI 36336366399](https://github.com/nazeeh111/SchemaRehearsal/actions/runs/36336366399) passed on source commit `fa99fc8369c731f8135904e04047b47f66e3d111` on Linux with Python 3.11 and 3.14. Each job passed all 26 tests, source compilation, wheel build, and an installed CLI run outside the checkout with broken/repaired/unchanged exits 1/0/0. The final release adds documentation and source-distribution inclusions; runtime code and tests are unchanged. Local testing does not establish production workload coverage, arbitrary database-engine compatibility, malicious-input containment, a hard total memory bound or directory-wide immutability. Source connections are read-only, but SQLite coordination sidecars and concurrent writers are outside the directory-byte guarantee.

The standalone report was inspected in Chrome at desktop and 390-pixel widths. Narrow tables scroll horizontally with a visible hint and keyboard-focusable region. This manual check is not an accessibility certification.

The post-release [duplicate-row walkthrough](walkthrough.md) was executed with
the downloaded v0.1.0 wheel in an isolated environment with `PYTHONPATH` unset.
Reordering A/A/B to B/A/A matched (exit 0); replacing one A with B changed
(exit 1). Both retained three rows, the same distinct SKUs, and passing database
checks. The recipe verifies exit codes and both observation results. CI now
also runs this recipe with its installed wheel; that configuration alone is
not a claim of a passed hosted run.
