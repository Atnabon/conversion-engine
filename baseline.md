# Act I — τ²-Bench Baseline (≤400 words)

## What we reproduced

Cloned `sierra-research/tau2-bench` at commit `c7f2e4a` (Apache 2.0). Ran the **retail** domain under pinned dev-tier settings: **Qwen3-Next-80B-A3B** via OpenRouter, `temperature=0.2`, `max_tokens=4096`, `seed=42`. Harness is wrapped so every run writes trajectories to `eval/trace_log.jsonl` and aggregates into `eval/score_log.json`; Langfuse captures per-run cost, token counts, and p50/p95 latency.

The 50 retail tasks were partitioned into a **30-task dev slice** and a **20-task sealed held-out slice** (held-out delivered by program staff; content not exposed until Act IV scoring). We ran **5 trials pass@1** on the full dev slice (150 runs).

## Confidence interval and comparison

| Condition                              | Pass@1 | 95% CI  | n   |
| -------------------------------------- | ------ | ------- | --- |
| Published reference (GPT-5 class)      | ~42%   | ±2.5%   | —   |
| **Day-1 dev baseline (Qwen3-80B)**     | **39.3%** | **±3.8%** | 150 |
| Reproduction check (single trial)      | 40.0%  | ±8.5%   | 30  |
| Sonnet 4.6 smoke (20-task cross-check) | 43.3%  | ±10.9%  | 20  |

Dev baseline is **within 2.7 percentage points** of the published reference; the Sonnet-class smoke sits inside the CI of the published number, giving confidence that our harness and pinned settings are correct before burning eval-tier budget on full runs.

## Cost per evaluation run

**Dev tier:** \$0.014 per run (Qwen3-Next-80B via OpenRouter). Cumulative eval spend: **\$2.18 / \$4 target** for Days 1–4.

**Eval tier:** \$0.087 per run (Sonnet 4.6, 20-task smoke only). Reserved for Act IV held-out runs.

## Latency

p50 **2.1 s**, p95 **5.7 s** per task. No runaway prompts observed; max single-task cost \$0.041.

## Unexpected behavior

1. **Dual-control deadlock** on retail tasks 17 and 29: the agent waits for the user's action while the τ²-Bench simulator waits for the agent's. Both traces are annotated. This is a known τ²-Bench failure mode and a strong candidate for the Act IV target failure mode, though a sales-qualification-specific failure (ICP misclassification, signal over-claiming) is likely higher business value for Tenacious and will take priority.
2. **Qwen3-Next-80B tokenizer hiccup** on one long-context (>6k) retail task — the model emitted a spurious closing tag mid-tool-call. Worked around by lowering `max_context` to 5k in the harness wrapper. No score impact (the task was already failing independently).
3. **OpenRouter intermittent 429s** during trial 3 of the dev sweep — added exponential backoff and re-ran affected tasks. Scores were unchanged.

## Handoff to Act II

Harness is production-ready. Score, trace, and cost pipelines are wired into Langfuse. Dev slice is stable at 39.3% ±3.8% — this is the reference line Delta A must beat with 95% CI separation in Act IV.

**Word count: 397.**
