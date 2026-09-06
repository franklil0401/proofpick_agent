# Original exposed15 real-provider retest

Fixed production: `bad83ea7512e6b53ae554bbd4a1f80f0c3f4f715`;
tree `5f3bdc6f50ec4ad71636ac745d31881f4323f7ed`.
Evaluation branch: `eval/v2-trusted15-repair-check`.

This round retests only the original Monitor 012--026 questions from the frozen
independent pool, not the developer's reconstructed Fake questions. The previous
real result remains 4/15 on production `02e97a2`. The remaining 64 questions are
out of scope and must not execute. No new Holdout or overall release conclusion.

## Protocol and acceptance

- Preserve original input, gold, scorer and the authorized citation adapter.
- Freeze selection, hashes, runtime contracts and runner before paid calls.
- Use the real default HTTP Portfolio API through in-process ASGI transport.
- Match documented environment, without hidden engine switches. New session per
  task, long-term memory off, existing index reused, no checkpoint or answer cache.
- Each original task gets one new real execution in this explicitly authorized
  exposed-regression round. Write and fsync sanitized raw output before scoring.
- Ordinary failures continue. Safety, evaluator errors, identity changes, unknown
  usage accounting and budget failure stop. No production repair or paid replay.
- Phase budget CNY 1.00, reserve CNY 0.20 before a new task, per-task timeout 180s.
- Report 15/15 only if every original task passes with zero safety findings.
- Check the prior critical case has real pending questions, zero paid calls,
  zero business tools and zero recommendations; a nonempty status string alone
  is insufficient evidence of clarification. This corroborates the old criterion.
- Report phase denominators, constraints, evidence, failures, calls, cost and
  latency separately from old results; 0/0 is N/A.
- Do not modify protected refs, original data/tests/evaluations, or create a
  PR/Tag/Release. Commit/push only this independent evaluation branch.

## Artifacts and reproduction

The primary user artifact remains Markdown, as in the established handoff.
Exact JSON records and Python evaluation modules are the reproducible companion;
a duplicate notebook or decorative quantitative chart is unnecessary for 15 tasks.
The technical report separates observed regression improvement from untested
generalization and includes definitions, methods, caveats and next steps.

From the root with `PYTHONPATH` set to the root, use the frozen vendor environment:
`python -m smartbuy.eval.trusted15_repair_independent.freeze` (write-once), commit
the resulting freeze, then run `python -m smartbuy.eval.trusted15_repair_independent.run`.
Existing result files prohibit another run. Offline reassessment uses
`python -m smartbuy.eval.trusted15_repair_independent.audit` without model calls.

Sources: [original evaluator](../v2_9i_independent/README.md),
[previous real results](../trusted79_independent/results/first_scores.json).
