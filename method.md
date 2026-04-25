# Method — Signal-Confidence-Aware Phrasing with Compose-time Honesty Gate

This document is the design record for the Act IV mechanism. It is written so an engineer with the repo and `data/schemas/hiring_signal_brief.schema.json` could re-implement it from this document alone.

## What it does

The mechanism inserts two deterministic checks between the enrichment pipeline's output and the LLM-driven outreach draft:

1. **Honesty Gate** — reads the brief's `honesty_flags`, `*_confidence`, and `velocity_label` fields and writes a `phrasing_directive` into the LLM compose prompt. The directive forces a specific phrasing register on every signal that is below confidence threshold.
2. **Tone-Preservation Re-check** — after the first draft, runs a second LLM call that scores the draft against the five tone markers from `data/seed/style_guide.md`. A draft scoring < 4/5 on any marker triggers regeneration (max 2 retries) with the failed-marker name appended to the directive.

Together the two checks address the C2 root cause from `probes/target_failure_mode.md` — the composer is not reading `*_confidence` and `honesty_flags` reliably — by removing the LLM's option to phrase a low-confidence signal as a high-confidence one.

## Why it addresses the root cause

The C2 failure pattern is not "the LLM is bad at tone". It is "the LLM is given a brief that contains confidence fields and asked to write a draft, but nothing in the prompt forces it to consult the confidence". Empirically (probe library §C2), the LLM ignores the confidence ~21% of the time when the signal is provocative.

The mechanism removes that option. The Honesty Gate compiles confidence and honesty_flag values into a prescriptive `phrasing_directive` string that:
- forbids assertion verbs ("you are scaling", "your hiring tripled") for any signal where `signal_confidence < 0.6`;
- replaces them with question registers ("you have N open roles since X — is hiring velocity matching the runway?");
- attaches a per-signal `honesty_clause` that the LLM must include verbatim if the corresponding `honesty_flag` is set in the brief.

The Tone-Preservation Re-check is a downstream catch — it does not solve the root cause but reduces the residual error rate on cases where the directive itself is misread. It is included as a layered defense, not as a substitute for the gate.

## Hyperparameters (actual values used)

| Parameter | Value | Rationale |
| --------- | ----- | --------- |
| `HONESTY_GATE_CONFIDENCE_THRESHOLD` | **0.60** | Same threshold as ICP abstention in `agent/enrichment/pipeline.py::_segment_classification`. Picked to align the two abstention decisions on a single number. |
| `HONESTY_GATE_HIGH_CONFIDENCE_PHRASES` | banned set: `{"scaling aggressively", "tripled", "you're hiring fast", "clearly", "obviously"}` | Sourced from `seed/style_guide.md` "Bad" examples. |
| `TONE_CHECK_PER_MARKER_THRESHOLD` | **4 / 5** | Aligned with the style guide §"How to test your outputs" rule. |
| `TONE_CHECK_MAX_RETRIES` | **2** | One regeneration costs ~\$0.02; two retries cap the per-draft cost at 3× normal. Above 2, escalate to a human. |
| `BENCH_GATE_HARD_LIMIT` | bench_summary count | Per `bench_summary.json.honesty_constraint`, no soft limit — hard cap. |
| `LLM_DEV_TIER_TEMPERATURE` | **0.2** | Pinned (matches Act I baseline). |
| `LLM_EVAL_TIER_TEMPERATURE` | **0.0** | Pinned (matches Act I baseline). |

## Three ablation variants

Each ablation removes or replaces one component to test what part of the lift comes from where. Run on the same 30 dev tasks, 5 trials each, against the same pinned dev-tier model.

### Ablation A — Honesty Gate only (no tone re-check)

- **Change.** Remove the Tone-Preservation Re-check; keep the Honesty Gate.
- **Tests.** Whether the lift is driven by the directive itself or by the regeneration loop.
- **Hypothesis.** Honesty Gate alone delivers most of the Delta A; tone re-check adds <1 pp at >50% of the cost overhead.

### Ablation B — Tone re-check only (no honesty gate)

- **Change.** Remove the Honesty Gate; keep the Tone Re-check.
- **Tests.** Whether downstream filtering can substitute for upstream prompt shaping.
- **Hypothesis.** Negative — tone re-check has no insight into signal confidence and cannot rewrite a confidently-wrong claim into an inquisitive one.

### Ablation C — Strict mode (no temperature)

- **Change.** Force `temperature=0.0` on the dev-tier model with the full mechanism.
- **Tests.** Whether residual errors are sampling noise or systematic.
- **Hypothesis.** Pass@1 inches up by 1–2 pp; cost-per-run unchanged; reveals which probe fires are sample-noise (fixed by T=0) vs systematic (still firing).

## Statistical test plan

**Test.** Paired bootstrap over the 30-task dev slice with 10,000 resamples. For each resample, compute the per-task pass-rate difference between method and Day-1 baseline; the **Delta A** point estimate is the mean, with 95% CI taken as the 2.5th and 97.5th percentiles of the bootstrap distribution.

**Comparison.** `method` vs `day1_baseline` on the **sealed held-out slice** (not the dev slice — the dev slice was used to pick hyperparameters, so a held-out comparison is required for an honest Delta A). 5 trials × 20 tasks = 100 simulations per condition.

**Decision rule.** Delta A is **claimed positive with 95% CI separation** if the lower bound of the bootstrap CI on the held-out slice is ≥ 0. Equivalently, **p < 0.05 under a one-sided paired bootstrap test** with the null hypothesis `Delta A ≤ 0`.

**Threshold.** A Delta A whose lower CI is below zero is reported as "no significant lift" with the point estimate and CI shown — the spec's anti-overclaim rule applies. The challenge text confirms `failing Delta B does not fail the week` but unexplained negative Delta A would.

## Re-implementation outline (so an engineer can re-build this)

```python
# agent/composer.py (new)

def build_phrasing_directive(brief: dict) -> str:
    directive_lines = ["Use grounded, confidence-aware phrasing."]

    # Hiring velocity
    velocity = brief["hiring_velocity"]
    if velocity["signal_confidence"] < HONESTY_GATE_CONFIDENCE_THRESHOLD:
        directive_lines.append(
            f"DO NOT assert hiring velocity. The signal is below confidence "
            f"threshold (sources: {velocity.get('sources', [])}). "
            f"Frame as a question that names the {velocity['open_roles_today']} "
            f"open roles since the prior snapshot."
        )

    # AI maturity
    ai = brief["ai_maturity"]
    if ai["score"] >= 2 and ai["confidence_label"] == "low":
        directive_lines.append(
            "AI maturity score is mid (2-3) but confidence is low. "
            "Phrase AI references as questions ('is that right?'), not as "
            "assertions about the prospect's AI function."
        )

    # Honesty flags
    for flag in brief.get("honesty_flags", []):
        directive_lines.append(HONESTY_FLAG_DIRECTIVE_MAP[flag])

    return "\n".join(directive_lines)


def compose_with_honesty_gate(brief: dict, segment: str) -> str:
    directive = build_phrasing_directive(brief)
    draft = llm.complete(
        prompt=COMPOSE_PROMPT.format(brief=brief, segment=segment, directive=directive),
        temperature=LLM_DEV_TIER_TEMPERATURE,
    )
    return tone_preserve(draft, max_retries=TONE_CHECK_MAX_RETRIES)


def tone_preserve(draft: str, *, max_retries: int) -> str:
    for attempt in range(max_retries + 1):
        scores = llm_score_against_markers(draft)  # five markers, 1-5 each
        failed = [m for m, s in scores.items() if s < TONE_CHECK_PER_MARKER_THRESHOLD]
        if not failed:
            return draft
        if attempt == max_retries:
            log_and_escalate_to_human(draft, failed)
            return draft
        draft = llm.complete(
            prompt=REGENERATE_PROMPT.format(draft=draft, failed_markers=failed),
            temperature=LLM_DEV_TIER_TEMPERATURE,
        )
    return draft
```

`HONESTY_FLAG_DIRECTIVE_MAP` is a static dict keyed on the enum from `data/schemas/hiring_signal_brief.schema.json::honesty_flags` — six entries, one directive per flag. Stored alongside the composer.

## Integration with the rest of the codebase

- `agent/enrichment/pipeline.py` already emits `honesty_flags` and per-signal confidence. No change.
- `agent/composer.py` (new) wraps the existing draft path. Email and SMS handlers call `compose_with_honesty_gate` instead of a raw LLM call.
- `agent/tools/hubspot_mcp.py` already writes confidence labels — extends to also write `compose_directive_used` so the analyst can see *why* a draft was inquisitive vs assertive.
- The mechanism is end-to-end testable through the same `tests/test_enrichment_pipeline.py` shape; a new `tests/test_composer_honesty_gate.py` asserts that:
  1. Briefs with `weak_hiring_velocity_signal` flag produce drafts containing question marks and not the banned-phrase set;
  2. Briefs with all signals at confidence ≥ 0.8 produce assertive drafts (regression guard);
  3. Tone re-check rejects drafts with two banned phrases and accepts drafts that pass all five markers.

## Expected outcomes

The pre-implementation expectation, recorded so the post-run write-up can be checked against it without revisionism:

| Metric | Pre-run estimate |
| ------ | ---------------- |
| Delta A (held-out) | **+3 to +6 pp** (point estimate ~+4 pp) |
| Cost overhead per draft | +\$0.012 (one extra LLM call for tone re-check ~60% of the time) |
| Latency overhead per draft | +1.5 s p50 |
| Probe coverage moved from "fires" to "blocked" | C2 (8 probes), partial coverage on C9 and C10 |

Actual numbers post-run will populate `eval/ablation_results.json` and the §6 table of the final memo.
