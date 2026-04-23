# Act I — τ²-Bench Retail Baseline (≤400 words)

## What was reproduced

Cloned `sierra-research/tau2-bench` at commit `d11a9707` (Apache 2.0) and ran the **retail** domain against the pinned dev-tier configuration (model, temperature, and seed fixed by program staff on Day 0 — see `configs/pinned_models.yaml`). The harness wrapper persists every simulation trajectory to `eval/trace_log.jsonl` and aggregates the run into `eval/score_log.json`. 5 trials × 30 dev-slice tasks = **150 evaluated simulations, 0 infra errors**.

The 50-task retail partition is split 30 dev / 20 held-out, as instructed; the held-out slice was received from program staff via encrypted channel and is not touched in Act I.

## Pass@1 and confidence interval

| Metric | Value | Source |
| ------ | ----- | ------ |
| Evaluated simulations | 150 | `eval/score_log.json` |
| Total tasks × trials | 30 × 5 | `eval/score_log.json` |
| **pass@1** | **0.7267 (72.67%)** | `eval/score_log.json` |
| 95% CI | [0.6504, 0.7917] | Wilson score on 150 Bernoulli outcomes |
| Infra errors | 0 | `eval/score_log.json` |

This is the reference line that Delta A must beat with 95% CI separation in Act IV. Every subsequent mechanism score is compared against this number on the same pinned harness, the same seed, and the same 30 dev tasks.

## Cost per run

| Metric | Value |
| ------ | ----- |
| **Average agent cost per run** | **$0.0199** |
| Aggregate cost over 150 runs | ~$2.99 |
| Dev-tier budget target (Days 1–4) | ≤ $4.00 |

Eval-tier budget is untouched; Claude Sonnet 4.6 is gated to the sealed held-out slice in Act IV only.

## Latency

| Metric | Value |
| ------ | ----- |
| p50 per simulation | 105.95 s |
| p95 per simulation | 551.65 s |

Latency is dominated by the τ²-Bench simulator's turn loop, not by LLM tokens — the retail tasks average ~14 turns, and each turn adds an LLM round-trip plus simulator tool-call latency.

## Unexpected behaviour

1. **Long tail in p95.** A handful of simulations run 5–7× the p50, all on tasks that hit the τ²-Bench dual-control failure mode (agent waits for user while simulator waits for agent). `termination_reason` in `eval/trace_log.jsonl` tags these — they become candidate probes for Act III.
2. **Reward distribution is bimodal**, not graded — retail scoring collapses to {0.0, 1.0} per `reward` in the trace. This is expected by the τ²-Bench paper but worth stating so the CI interpretation uses a Bernoulli model, not a normal approximation.
3. **Uniform cost per run.** Per-run agent cost variance is small (σ ≈ \$0.005); no runaway-token prompt observed. No cost-pathology probe fires on this baseline.

## Handoff to Act II

The harness, score aggregator, and trace persistence are production-stable. **72.67% ± ~7%** is the reference against which Act III ablations and the Act IV mechanism measure Delta A.

**Provenance.** τ²-Bench commit `d11a97072c49d093f7b5a3e4fe9da95b490d43ba`, trials per task: 5.

**Word count: 386.**
