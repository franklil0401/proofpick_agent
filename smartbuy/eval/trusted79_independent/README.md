# Fixed-production Trusted79 continuation

This is an independent continuation of the original RC3 task pool, not a new
Holdout and not a repetition of the eleven already executed Monitor questions.
The developer did not receive the remaining inputs or gold for repair. The
evaluator originally authored the pool; this is not double-blind testing.

Production: `02e97a2c793ba75dfad5ece15e5df665652808bf`, tree
`7e6b036bc3255714cd378e887ae8b9779a5ef98a`.
Starting evaluation commit: `f0e8989c6667e3c1e7daa5bce296189416618910`.

## Protocol

- Read the original frozen cases, gold and additive citation adapter without edits.
- Select the original 90 minus the eleven IDs in the original execution records.
- Freeze each selected case, input, gold and execution order before model calls.
- Use HTTP POST `/api/smartbuy/portfolio/run` through in-process ASGI transport,
  real model providers and existing verified indexes. This does not test TCP,
  browser rendering, deployment concurrency or public authentication.
- Follow the documented default product routes. No hidden orchestration switches.
- Memory is disabled and each question gets a new session. No checkpoint recovery
  or hot-answer-cache reuse; index reuse is intentional.
- Call each task once. Persist and fsync the sanitized raw response before scoring.
- Ordinary functional failures continue. Safety, unknown accounting, identity or
  freeze mismatch, budget and scorer failures stop. No paid replay.
- Pure serialization/citation compatibility repair is authorized only as an
  additive, versioned evaluator revision with saved-output reassessment. Gold,
  semantics and safety criteria remain immutable.
- Budget is CNY 3, with CNY 0.25 reserved before starting the next task; no Online.
- No production/data/index edits, protected branch updates, PR, Tag or Release.

## Metrics

Task correctness retains the original scorer semantics. Report executed and
planned denominators separately; unrun tasks are neither passes nor failures.
Micro constraint precision/recall/F1 sum TP/FP/FN, not case averages. No denominator
means N/A. Recommendation evidence uses the original unique product/field claims;
fact/comparison requested-field evidence is also reported separately. Sufficient-
data empty-recommendation rate is empty outputs over executed positive filters.

Phase gate requires all 79 completed, Monitor at least 16/19, Laptop at least
24/30, Headphone at least 24/30, micro hard-constraint F1 at least 0.95,
recommendation evidence coverage at least 0.95, and zero original safety findings.
Passing this phase alone does not establish a full new 90-task release result.

## Reproduction

From the repository root, set `PYTHONPATH` to that root and use the frozen vendor
environment. `python -m smartbuy.eval.trusted79_independent.freeze` creates
exclusive freeze artifacts. Commit them before running
`python -m smartbuy.eval.trusted79_independent.run`. Existing result files prevent
another run. `python -m smartbuy.eval.trusted79_independent.audit` only recomputes
saved-output scores and makes no model calls. The Python modules and exact raw
records are the reproducible companion instead of a duplicate notebook.

References: [original evaluator](../v2_9i_independent/README.md),
[prior four-case retest](../fact_completion_independent/README.md).
