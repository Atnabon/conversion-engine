# Failure Taxonomy

Every probe from [`probe_library.md`](probe_library.md) is grouped into exactly one category. No orphan probes, no double-counting. The aggregate trigger rate per category is the unweighted mean over the probes it contains. The shared-pattern description names the *kind* of failure the agent is making, not the symptom — that is what makes the taxonomy useful for picking a target failure mode.

| Category | Probes (32 total) | Aggregate trigger rate | Shared pattern |
| -------- | ----------------- | ---------------------- | -------------- |
| **C1 · ICP misclassification** | P-001, P-002, P-003, P-004 | **0.19** | Agent classifies on a single dominant signal and ignores conflicting signals from other sources. The failure is in the *combination* logic of `agent/enrichment/pipeline.py::_segment_classification`, not in any individual signal. |
| **C2 · Hiring-signal over-claiming** | P-005, P-006, P-007, P-008 | **0.21** | Agent asserts the value of a signal whose `signal_confidence` is < 0.6, OR invents a value not present in the brief. The composer is not reading `honesty_flags` from the brief reliably. |
| **C3 · Bench over-commitment** | P-009, P-010, P-011 | **0.16** | Agent commits to capacity beyond what `data/seed/bench_summary.json` shows, OR mis-reads `time_to_deploy_days` against regulated-industry rules. The bench guard fires too late in the compose pipeline (after the draft is already written). |
| **C4 · Tone drift from style guide** | P-012, P-013, P-014, P-015 | **0.19** | Agent matches a prospect-set tone that drifts away from the five tone markers. The tone-preservation check is run only once on the first draft and not again on regenerations. |
| **C5 · Multi-thread leakage** | P-016, P-017, P-018 | **0.10** | Conversation context is keyed on `prospect_email` rather than `(prospect_email, thread_id, run_id)`. Two threads at the same company / domain bleed enrichment data across each other. |
| **C6 · Cost pathology** | P-019, P-020, P-021 | **0.10** | Per-turn cost climbs unbounded under specific inputs (long context, repeated tone-check failures, verbose justification fields). No backoff or token budget gate. |
| **C7 · Dual-control coordination** | P-022, P-023, P-024 | **0.11** | Agent and simulated user (or real user) end up in the τ²-Bench-style waiting deadlock — each waiting on the other to act. Surfaces in retail-style transactional turns. |
| **C8 · Scheduling edge cases** | P-025, P-026, P-027 | **0.15** | Time-zone arithmetic at booking time. Agent does not normalise to UTC then localise per attendee; mishandles DST and east-of-UTC zones. |
| **C9 · Signal reliability (FP/FN)** | P-028, P-029, P-030 | **0.18** | Public-signal data is treated as ground truth. Absence is interpreted as proof of absence; staleness is not flagged. The system has no calibration on its own scoring. |
| **C10 · Gap over-claiming** | P-031, P-032 | **0.15** | Agent asserts gaps that are not supported by the competitor brief, OR doubles down on a gap when the prospect pushes back. Same root cause as C2 but applied to the competitor brief instead of the hiring brief. |

## Cross-cuts

Two structural observations that the per-category view misses:

1. **C2 + C9 + C10 share a root cause** — every "over-claiming" failure boils down to the composer not reading `*_confidence` and `honesty_flags` fields from the brief before phrasing. A single fix at the compose layer addresses ~22% of total trigger weight (8 of 32 probes).
2. **C5 + C7 + C24 (P-024) are observability failures** — the system reports a state to the user that isn't true (cross-thread context leak, claimed-but-not-executed tool call). These are harder to fix because they require log-and-replay tooling we have not yet built.

## Selection driver

The category-level numbers feed [`target_failure_mode.md`](target_failure_mode.md). The argument there ranks candidates on **trigger-rate × Tenacious-specific business cost**, not trigger rate alone — that's why C2 (signal over-claiming) wins over C7 (dual-control coordination) despite both being plausible targets.
