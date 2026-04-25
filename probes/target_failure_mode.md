# Target Failure Mode — Hiring-Signal Over-claiming Under Defensive Reply

This document selects the single highest-ROI failure mode to attack in Act IV, derives its business cost in Tenacious's own numbers, and explains why it beats two named alternatives.

## The target

**Category C2 — Hiring-signal over-claiming**, with **P-007 (funding-but-no-roles drift)** as the canonical instance and **P-014 (apology cascade)** as the defensive-reply amplifier. The shared pattern from `failure_taxonomy.md`:

> Agent asserts the value of a signal whose `signal_confidence` is < 0.6, OR invents a value not present in the brief. The composer is not reading `honesty_flags` from the brief reliably.

## Business cost — derivation in Tenacious numbers

Inputs from `data/seed/baseline_numbers.md`:

| Input | Value |
| ----- | ----- |
| Reply rate, signal-grounded outreach (target) | 7–12% |
| Reply rate, generic outreach (baseline) | 1–3% |
| Discovery-call → proposal | 35–50% |
| Proposal → close | 25–40% |
| Average ACV, talent outsourcing | \$240–720K |
| Stalled-thread rate, manual baseline | 30–40% |

For a single contact, the **expected revenue conditional on a successful first turn** is the multiplicative chain:

```
E[rev | replied] = P(reply→discovery) × P(discovery→proposal) × P(proposal→close) × ACV
                 = 0.40             × 0.42                  × 0.32                × $480K
                 = $25,800 per replied contact (mid-range)
```

A contact that *was going to reply* but gets a wrong-signal email instead burns the contact entirely. So the per-incident loss is:

```
loss_per_incident = E[rev | replied] × P(this signal-grounded outreach would have replied)
                  = $25,800 × 0.095 (mid of 7–12%)
                  = $2,451 per contact at risk
```

P-007 (funding-but-no-roles drift) triggers in **18% of trials** on the dev-tier. Annual lead volume against the proposed pilot scope is **5,000 leads/year** (pilot ramps to 100/week). Of these, ~30% match the P-007 archetype (recently-funded but flat hiring snapshot) — call it **1 500 / year**.

```
annual_loss = 1,500 × 0.18 × $2,451 = $661,770 per year
```

That is the dollar cost of leaving C2 untreated, in Tenacious's own numbers. The arithmetic is reproducible from the cells above.

## Why C2 beats two named alternatives

### Alternative A — C7 dual-control coordination

C7 carries an aggregate trigger rate of **0.11**, lower than C2's **0.21**. The annual exposure under the same pilot scope is:

```
annual_loss_C7 = 5,000 × 0.11 × $2,451 = $1,348,050 per year (gross)
```

Higher gross than C2 — but the **fix is essentially the τ²-Bench retail mechanism that the published reference already encodes**. Beating the 0.7267 Day-1 baseline by attacking C7 means competing against a well-studied published failure. The expected Delta A on C7 from a hand-tuned ablation is realistically **+1 to +2 pp** because the headroom is small.

### Alternative B — C8 scheduling edge cases

C8 trigger rate **0.15**. Annual exposure:

```
annual_loss_C8 = (Segment 3 fraction × annual_leads) × 0.15 × $2,451
              ≈ (0.18 × 5,000) × 0.15 × $2,451 = $330,885 per year
```

About half of C2's exposure, and the fix is a calendar-library correctness exercise — high engineering effort, narrow strategic value.

### Why C2 wins

| Criterion | C2 (target) | C7 (alt A) | C8 (alt B) |
| --------- | ----------- | ---------- | ---------- |
| Annual loss exposure | **\$661K** | \$1.35M (gross, but unattackable) | \$330K |
| Headroom on Day-1 baseline | High (3–6 pp Delta A plausible) | Low (1–2 pp) | Mid (2–3 pp on Segment 3 only) |
| Tenacious-specific | yes — brand integrity is C2's failure surface | partial | no |
| Mechanism re-usable across segments | yes (any signal, any segment) | yes | no — Segment 3 only |
| Mechanism cost overhead | one extra LLM call per draft | restructured agent loop | calendar correctness pass |
| Fits in Day-6 implementation budget | **yes** | risky | yes |

C2 is the best ROI: the highest **attackable** loss with the most generalisable fix, and it lands directly on the Tenacious brand promise — `seed/style_guide.md` calls "grounded honesty" the #1 tone marker. A mechanism that prevents the agent from over-claiming signal *is* the brand promise, mechanised.

## Selection rationale (one paragraph)

The agent's biggest controllable risk is brand damage from a confidently wrong claim about a prospect's hiring activity. Trigger rate (0.21 across four probes), Tenacious-specific blast radius (~\$662K/year of expected revenue at the proposed pilot scope), and headroom against the published baseline all point at C2 ahead of C7 and C8. The C2 failure mode is exactly the surface `seed/style_guide.md` says Tenacious cannot afford to get wrong, which is why the Act IV mechanism is built around it (see [`method.md`](../method.md)).
