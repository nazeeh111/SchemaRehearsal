"""Bounded deletion of scenario step ranges using the rehearsal contract."""

from copy import deepcopy
import time

from .engine import Limits, RehearsalError, _rehearse_for_minimization, validate_suite


def minimize(database, migration, suite, *, scenario, observation=None, commit=False,
             max_trials=100, seconds=60, limits=None, allow_fts5=False):
    """Return (reduced suite, summary); witness is explicitly named or commit.

    Observation identity is the exact private normalized before/after pair.
    Trials with invalid baselines or execution errors are inconclusive.
    """
    limits = limits or Limits()
    validate_suite(suite, limits)
    if bool(observation) == bool(commit):
        raise RehearsalError("Select exactly one observation or commit witness.")
    if type(max_trials) is not int or not 1 <= max_trials <= 10000:
        raise RehearsalError("Trial budget must be an integer from 1 to 10000.")
    if type(seconds) not in (int, float) or not 0 < seconds <= 3600:
        raise RehearsalError("Time budget must be greater than 0 and at most 3600 seconds.")
    cases = [case for case in suite["scenarios"] if case["name"] == scenario]
    if len(cases) != 1:
        raise RehearsalError("Selected scenario does not exist.")
    case = deepcopy(cases[0])
    if commit and case.get("transaction") != "commit":
        raise RehearsalError("Commit witness requires a commit scenario.")
    if observation and not any(x["name"] == observation for x in case["observations"]):
        raise RehearsalError("Selected observation does not exist.")
    reduced = {"format": suite["format"], "scenarios": [case]}
    started = time.monotonic()
    trials = 0
    inconclusive = 0

    def run(candidate):
        nonlocal trials
        remaining = seconds - (time.monotonic() - started)
        if trials >= max_trials or remaining <= 0:
            return None
        trials += 1
        trial_limits = Limits(database_bytes=limits.database_bytes, input_bytes=limits.input_bytes,
                              result_bytes=limits.result_bytes, result_rows=limits.result_rows,
                              seconds=min(limits.seconds, remaining))
        return _rehearse_for_minimization(database, migration, candidate, scenario=scenario,
                                          observation=observation, limits=trial_limits,
                                          allow_fts5=allow_fts5)

    def witness(result):
        report, pair = result
        if report["status"] not in ("matched", "changed") or len(report["scenarios"]) != 1:
            return None
        result = report["scenarios"][0]
        if commit:
            value = result["commit"]
        else:
            value = next(x for x in result["observations"] if x["name"] == observation)
        if value["equal"] or (not commit and pair is None):
            return None
        return (value, None if commit else pair)

    original = run(reduced)
    if original is None or witness(original) is None:
        raise RehearsalError("Selected witness is not a valid changed baseline rehearsal.")
    target = witness(original)
    snapshot = original[0]["snapshot_sha256"]
    repeat = run(reduced)
    if repeat is None:
        raise RehearsalError("Budget exhausted before witness stability check; no result written.")
    if repeat[0].get("snapshot_sha256") != snapshot or witness(repeat) != target:
        raise RehearsalError("Source snapshot or reported witness changed on repeat; no result written.")
    original_steps = len(case["steps"])
    width = original_steps
    index = 0
    stop = "complete"
    while width:
        # Leave enough trials for a full single-step pass, when possible.
        if width > 1 and max_trials - trials <= len(case["steps"]):
            width = 1
            index = 0
        if index >= len(case["steps"]):
            if width == 1:
                break
            # Split the ranges until the final pass tries every single deletion.
            width = (width + 1) // 2
            index = 0
        candidate = deepcopy(reduced)
        del candidate["scenarios"][0]["steps"][index:index + width]
        result = run(candidate)
        if result is None:
            stop = "budget_exhausted"
            break
        report = result[0]
        if "snapshot_sha256" in report and report["snapshot_sha256"] != snapshot:
            raise RehearsalError("Source snapshot changed during reduction; no result written.")
        if report["status"] not in ("matched", "changed"):
            inconclusive += 1
        elif witness(result) == target:
            reduced = candidate
            case = reduced["scenarios"][0]
            width = min(width, len(case["steps"]))
            index = 0
            continue
        index += width
    if stop == "complete" and inconclusive:
        stop = "inconclusive"
    summary = {"format": "schema-rehearsal/minimization-v1", "status": stop,
               "scenario": scenario, "witness": {"kind": "commit" if commit else "observation",
               "name": observation, "reported_outcome": target[0]},
               "original_steps": original_steps, "remaining_steps": len(case["steps"]),
               "trials": trials, "inconclusive_trials": inconclusive,
               "snapshot_sha256": snapshot, "migration_sha256": original[0]["migration_sha256"],
               "suite_sha256": original[0]["suite_sha256"]}
    return reduced, summary
