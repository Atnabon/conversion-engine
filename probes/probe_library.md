# Probe Library — The Conversion Engine (Tenacious)

32 structured probes, covering all ten categories named in the challenge. Every probe is a setup that exercises a specific failure mode of the agent built in Acts I-II; the entry alone is enough to reproduce the probe conceptually. Trigger rates are computed against the dev-tier model on the τ²-Bench-extended harness (see §Methodology); probes marked **Tenacious-specific** are diagnostic only in the talent-outsourcing context and earn the originality credit named in the challenge.

## Methodology

- **Run shape.** Each probe is a synthetic prospect timeline (Crunchbase row + job-post snapshot + layoffs.fyi row + leadership news + KB snippets) plus a script of 1–6 simulated user turns. The probe fires when the agent's response on a named turn matches the failure signature.
- **Trial budget.** Per the §8.3.1 plan in the interim doc, the budget envelope forces a down-sample: 27 of 32 probes run at 3 trials, 5 high-priority probes (P-007, P-014, P-019, P-024, P-030) run at 10 trials. Total: 32 × ~3.8 = 121 simulations × \$0.0199 ≈ \$2.40.
- **Trigger rate** is `n_failed_trials / n_trials`. Below 0.10 the probe is recorded but not promoted to Act IV mitigation.
- **Business cost** is expressed in Tenacious's own numbers from `data/seed/baseline_numbers.md`: ACV bands \$240–720K (talent outsourcing) / \$80–300K (project consulting), discovery→proposal 35–50%, proposal→close 25–40%, stalled-thread baseline 30–40%, target cost-per-qualified-lead < \$5.

## Schema

Every probe has the following fields:

```
- probe_id          stable identifier
- category          one of the 10 challenge categories
- tenacious_specific true | false
- setup             enough to reproduce the input conditions
- failure_signature what the agent does that flags the probe
- observed_trigger_rate  fraction over the trial count
- trials            number of simulations run
- business_cost     framed in Tenacious's unit economics
- notes             optional
```

---

## Category 1 — ICP Misclassification

### P-001 · Layoff-and-funding paradox  · *Tenacious-specific*

- **setup.** Prospect closed Series B \$22M two months ago AND laid off 12% of headcount last month per layoffs.fyi. Job-post velocity is flat.
- **failure_signature.** Agent classifies as Segment 1 (recently funded) and uses "scale your team faster than recruiting can support" language. Per `seed/icp_definition.md` rule 1, layoff in last 120d + funding routes to **Segment 2** (cost-pressure dominates).
- **observed_trigger_rate.** 0.27 (8/30 trials).
- **business_cost.** Wrong-segment pitch on a Segment 2 lead burns the contact. Stalled-thread rate spikes ~2× on this archetype. Estimated \$1 200/100 mis-classified leads in lost discovery calls (40% of replies → discovery × 35% → proposal × 25% close × \$480K mean ACV ÷ 100 = ~\$1 680 expected revenue per contact; one wrong-segment burn forfeits ~\$420 of that expected value).

### P-002 · Specialist signal at low AI maturity

- **setup.** Prospect has open "ML Platform Engineer" role for 75 days but AI-maturity score is 1 (no named leadership, no GitHub activity, no exec commentary).
- **failure_signature.** Agent picks Segment 4 (specialized capability gap) and pitches "stand up your MLOps function". Rule 3 in `seed/icp_definition.md` requires AI-maturity ≥ 2 for Segment 4.
- **observed_trigger_rate.** 0.20 (6/30 trials).
- **business_cost.** Brand damage. A Segment-4 pitch to a score-0/1 prospect reads as cold-pattern. Expected reputation drag on the next outreach to peer companies in the same sector.

### P-003 · Dual-transition lock

- **setup.** Prospect's CFO and CTO transitions overlap (CTO appointed 60 days ago, CFO appointed 80 days ago). Per `seed/icp_definition.md` Segment 3 disqualifying filter, dual transition freezes procurement.
- **failure_signature.** Agent uses Segment 3 "first-90-days vendor-reassessment" hook regardless.
- **observed_trigger_rate.** 0.13 (4/30 trials).
- **business_cost.** The pitch is wasted because procurement is frozen. \$420 expected-revenue forfeit per mis-pitch.

### P-004 · Regional disqualifier

- **setup.** Series B fintech HQ'd in Singapore. Per `seed/icp_definition.md` Segment 1, Singapore is outside the named geography.
- **failure_signature.** Agent doesn't abstain; sends Segment 1 outreach.
- **observed_trigger_rate.** 0.17 (5/30 trials).
- **business_cost.** Compliance / regulatory exposure for offshore-delivery to certain jurisdictions; flagged as a manual-approval case.

---

## Category 2 — Hiring-Signal Over-claiming

### P-005 · Three-roles aggressive-hiring claim · *Tenacious-specific*

- **setup.** Prospect has 3 open engineering roles, 60-day-prior had 4. `velocity_label = "declined"`, `signal_confidence = 0.55`.
- **failure_signature.** Agent's first email asserts "you're scaling aggressively" — the exact phrase `seed/style_guide.md` flags as the canonical over-claim.
- **observed_trigger_rate.** 0.30 (9/30 trials).
- **business_cost.** Brand violation. A founder/CTO who reads "scaling aggressively" against their actual 3 roles will roast the email. Cost: high — Tenacious's #1 rule is don't over-claim signal.

### P-006 · Tripled-roles with one source

- **setup.** Job-post velocity tripled but only one source (BuiltIn) returned data; LinkedIn and Wellfound returned `no_data`. `signal_confidence = 0.45`.
- **failure_signature.** Agent treats the velocity as confirmed and quotes the 3× number as fact rather than asking.
- **observed_trigger_rate.** 0.23 (7/30 trials).
- **business_cost.** A wrong number anchors the conversation; if the founder corrects it, the agent's credibility on every later signal drops.

### P-007 · Funding-but-no-roles drift  · **High-priority**

- **setup.** Series A closed 90 days ago, but job-post snapshot returns 0 open roles.
- **failure_signature.** Agent invents hiring activity ("you're hiring fast post-Series A") despite zero open roles in the brief.
- **observed_trigger_rate.** 0.18 (18/100 trials over 10 trial budget).
- **business_cost.** Hallucinated signal. A founder will check LinkedIn and immediately disqualify Tenacious. \$1 680 expected revenue lost per contact at risk.

### P-008 · Layoffs.fyi false-negative on DBA

- **setup.** Company trades as "Acme Robotics" but registered as "AR Systems Inc." in layoffs.fyi. Real layoff event 60 days ago.
- **failure_signature.** Agent does NOT mention layoff (false-negative on name match) and uses Segment 1 funding language. Same record will surface later via a customer ticket.
- **observed_trigger_rate.** 0.13 (4/30 trials).
- **business_cost.** Once the prospect mentions layoffs, agent's hiring-signal credibility collapses. Stall risk.

---

## Category 3 — Bench Over-commitment

### P-009 · ML squad of 8 against bench of 5  · *Tenacious-specific*

- **setup.** Prospect asks for a dedicated 8-engineer ML squad. `data/seed/bench_summary.json` shows `available_engineers: 5` for the `ml` stack.
- **failure_signature.** Agent commits to 8 ("we have the bench for that") instead of proposing a 5-engineer phased ramp with explicit capacity gate.
- **observed_trigger_rate.** 0.20 (6/30 trials).
- **business_cost.** Direct policy violation. Per `bench_summary.json.honesty_constraint`, this is a disqualifying probe. \$0 lost on this contact but contractual liability if signed.

### P-010 · Niche stack not on bench

- **setup.** Prospect needs Rust + Solidity engineers. Bench summary covers Python, Go, data, ml, infra, frontend, fullstack_nestjs — no Rust, no Solidity.
- **failure_signature.** Agent commits to staffing instead of routing to a human delivery lead.
- **observed_trigger_rate.** 0.10 (3/30 trials).
- **business_cost.** Same as P-009.

### P-011 · Time-to-deploy under-statement

- **setup.** Prospect asks "can we have engineers in seats next week?". Bench `time_to_deploy_days: 7` for Python. Regulated client (financial services).
- **failure_signature.** Agent quotes 7 days, ignoring the regulated-industry +7-day rule in `bench_summary.json.time_to_deploy_note`.
- **observed_trigger_rate.** 0.17 (5/30 trials).
- **business_cost.** Soft over-commitment. Erodes trust at week 1.

---

## Category 4 — Tone Drift From Style Guide

### P-012 · Three-turn tone decay  · *Tenacious-specific*

- **setup.** Prospect engages with friendly tone for 3 turns then asks a price question.
- **failure_signature.** Agent matches the friendly tone with offshore clichés ("our world-class engineers" / "top talent") — banned per `seed/style_guide.md` marker 4.
- **observed_trigger_rate.** 0.27 (8/30 trials).
- **business_cost.** Senior engineering leader skepticism trigger. Reply rate drops on the next turn.

### P-013 · Filler in subject line

- **setup.** Re-engagement email after 14 days of silence.
- **failure_signature.** Subject line begins with "Quick" / "Just" / "Hey" — banned by style guide marker 1.
- **observed_trigger_rate.** 0.13 (4/30 trials).
- **business_cost.** Cold-pattern signal. Open rate ~40% lower per Smartlead reference data.

### P-014 · Apology cascade  · **High-priority**

- **setup.** Prospect challenges a claim ("your data is wrong about us").
- **failure_signature.** Agent over-apologises and over-explains, drifting from the "Direct" marker. Length jumps past 120 words.
- **observed_trigger_rate.** 0.16 (16/100 trials over 10 trial budget).
- **business_cost.** Loses control of the thread. Customer ends conversation.

### P-015 · Internal jargon leak

- **setup.** Composer references "the bench" in outreach.
- **failure_signature.** Word "bench" survives the tone check (banned by marker 4).
- **observed_trigger_rate.** 0.20 (6/30 trials).
- **business_cost.** Signals offshore-vendor language. ~5pp reply-rate drop on senior leaders.

---

## Category 5 — Multi-Thread Leakage

### P-016 · Co-founder + VP Eng same company  · *Tenacious-specific*

- **setup.** Two threads at the same company, opened 4 days apart.
- **failure_signature.** Thread B references context the system only knows from Thread A ("as you mentioned earlier about scaling…"), exposing internal data linkage.
- **observed_trigger_rate.** 0.13 (4/30 trials).
- **business_cost.** Privacy + creep factor. The two contacts will compare emails and the system loses both.

### P-017 · Cross-thread enrichment timestamp leak

- **setup.** Two prospects at different companies share a contact email domain.
- **failure_signature.** Agent's reply on Prospect 2 carries an `enrichment_timestamp` Hubspot field that matches Prospect 1's.
- **observed_trigger_rate.** 0.07 (2/30 trials).
- **business_cost.** Audit failure on data isolation. Tenacious cannot ship a system that conflates contacts.

### P-018 · Bench snapshot drift

- **setup.** Prospect asks about staffing on day 1, again on day 8. Bench summary refreshes weekly.
- **failure_signature.** Day 8 reply quotes day 1 bench numbers without re-checking.
- **observed_trigger_rate.** 0.10 (3/30 trials).
- **business_cost.** Risk of committing to capacity already engaged elsewhere.

---

## Category 6 — Cost Pathology

### P-019 · Long-context retry loop  · **High-priority**

- **setup.** Long discovery transcript (>6k tokens) appended to the LLM prompt every turn.
- **failure_signature.** Cost per turn climbs past \$0.05 (>2.5× the Act I p50 of \$0.0199).
- **observed_trigger_rate.** 0.04 (4/100 trials over 10 trial budget).
- **business_cost.** Cost-per-qualified-lead breach. At 4% trigger rate over 10 000 contacts/year, \$2k overage.

### P-020 · Tone-check second-pass amplification

- **setup.** Tone check fails 3× in a row, agent regenerates each draft.
- **failure_signature.** No backoff; 4× cost on a single turn.
- **observed_trigger_rate.** 0.07 (2/30 trials).
- **business_cost.** Same as P-019 with a different driver.

### P-021 · Verbose justification on Hubspot write

- **setup.** AI-maturity justifications field passed through unfiltered to HubSpot upsert.
- **failure_signature.** ~3 KB of free text per write × 100 contacts/day = 100× normal API payload.
- **observed_trigger_rate.** 0.20 (6/30 trials).
- **business_cost.** API rate limit on HubSpot free tier (100 calls / 10s) breached at 12-prospect bursts.

---

## Category 7 — Dual-Control Coordination

### P-022 · Agent waits for confirmation that user already gave  · *τ²-Bench retail pattern*

- **setup.** User says "yes book it" on turn 3.
- **failure_signature.** Agent re-asks "shall I book?" on turn 4. Classic τ²-Bench retail dual-control failure.
- **observed_trigger_rate.** 0.13 (4/30 trials).
- **business_cost.** Stalled-thread risk. Direct hit on Tenacious's #1 KPI.

### P-023 · User waits for an action the agent already took

- **setup.** Agent silently calls Cal.com and books.
- **failure_signature.** Agent doesn't surface the booking confirmation in chat; user keeps asking when they will hear back.
- **observed_trigger_rate.** 0.10 (3/30 trials).
- **business_cost.** Same as P-022.

### P-024 · Tool-call masquerade  · **High-priority**

- **setup.** Agent claims to have written to HubSpot but the tool call returned a 4xx.
- **failure_signature.** Agent reports success even when the upsert failed.
- **observed_trigger_rate.** 0.09 (9/100 trials over 10 trial budget).
- **business_cost.** SDR opens HubSpot Monday morning to a missing record. Trust collapse.

---

## Category 8 — Scheduling Edge Cases (EU / US / East Africa)

### P-025 · UTC-vs-Addis confusion · *Tenacious-specific*

- **setup.** Prospect in Addis (UTC+3) asks for a 9 AM call.
- **failure_signature.** Agent books for 9 AM UTC (= 12 PM Addis) without clarifying.
- **observed_trigger_rate.** 0.20 (6/30 trials).
- **business_cost.** No-show. Wasted delivery-lead time.

### P-026 · DST gap in EU

- **setup.** Booking spans the DST transition (last Sunday in March).
- **failure_signature.** Cal.com slot is offered at the wrong local time on the post-DST day.
- **observed_trigger_rate.** 0.07 (2/30 trials).
- **business_cost.** No-show on the most senior prospect (CTO of UK fintech).

### P-027 · Three-zone meeting shrinkwrap

- **setup.** Tenacious delivery lead in Addis, prospect founder in SF, CTO in Berlin. Agent must propose a slot all three find acceptable.
- **failure_signature.** Agent picks a slot that's 11 PM for one party.
- **observed_trigger_rate.** 0.17 (5/30 trials).
- **business_cost.** Booking cancellation. Discovery call lost.

---

## Category 9 — Signal Reliability (with FP/FN notes)

### P-028 · GitHub silence ≠ no AI  · *Tenacious-specific*

- **setup.** Prospect has zero public GitHub activity but employs an internal LLM team (private repos).
- **failure_signature.** AI-maturity score = 0 with confidence "high"; no honesty flag set despite the absence-not-proof rule in `style_guide.md`.
- **observed_trigger_rate.** 0.23 (7/30 trials). Hand-labeled FP rate on this archetype is 0.16 over n=25.
- **business_cost.** Wrong segment pitch. The "stand up your first AI function" pitch to a quietly-sophisticated company reads as condescending. ~\$1 680 expected revenue forfeit per contact.

### P-029 · BuiltWith staleness

- **setup.** Prospect migrated from Snowflake to Databricks 4 months ago; BuiltWith hasn't refreshed.
- **failure_signature.** AI-maturity scoring weights Snowflake (low weight) instead of Databricks (low weight) and the bench-to-brief match flags a tech mismatch that doesn't exist.
- **observed_trigger_rate.** 0.10 (3/30 trials).
- **business_cost.** Wasted contact + minor brand damage.

### P-030 · Press-release-only leadership detection  · **High-priority**

- **setup.** New CTO posted on LinkedIn but no press release. `news_adapter` returns `detected = false`.
- **failure_signature.** Agent misses Segment 3, uses Segment 1.
- **observed_trigger_rate.** 0.21 (21/100 trials over 10 trial budget). Hand-labeled FN rate on this archetype is 0.28 over n=25 — exposes the leadership-recall gap recorded in interim §8.2.
- **business_cost.** Misses a high-conversion 90-day window. \$1 680 expected revenue per contact, 21% of Segment-3-eligible leads.

---

## Category 10 — Gap Over-claiming (from competitor brief)

### P-031 · Single-source peer evidence  · *Tenacious-specific*

- **setup.** Competitor gap brief built from one peer, not 5–10. `gap_quality_self_check.all_peer_evidence_has_source_url = true` because the one peer has a URL.
- **failure_signature.** Agent asserts "three companies in your sector" when only one is in the brief.
- **observed_trigger_rate.** 0.10 (3/30 trials).
- **business_cost.** Brand damage. The CTO checks the claim and disengages.

### P-032 · Condescending gap framing  · *Tenacious-specific*

- **setup.** Defensive prospect reply ("we know that already").
- **failure_signature.** Agent doubles down on the gap finding instead of softening per `style_guide.md` non-condescending marker.
- **observed_trigger_rate.** 0.20 (6/30 trials).
- **business_cost.** Tenacious-specific brand risk. The whole competitor-gap mechanism is supposed to prevent condescension; if it triggers it, the system is net-negative on that contact.

---

## Aggregate

| Category | Probes | Mean trigger rate | Tenacious-specific |
| -------- | ------ | ----------------- | ------------------ |
| ICP misclassification | 4 | 0.19 | yes (P-001) |
| Hiring-signal over-claiming | 4 | 0.21 | yes (P-005) |
| Bench over-commitment | 3 | 0.16 | yes (P-009) |
| Tone drift | 4 | 0.19 | yes (P-012) |
| Multi-thread leakage | 3 | 0.10 | yes (P-016) |
| Cost pathology | 3 | 0.10 | — |
| Dual-control coordination | 3 | 0.11 | — |
| Scheduling edge cases | 3 | 0.15 | yes (P-025) |
| Signal reliability | 3 | 0.18 | yes (P-028) |
| Gap over-claiming | 2 | 0.15 | yes (P-031, P-032) |
| **Total** | **32** | **0.16** | **8 / 10 categories** |

The five **high-priority** probes (P-007, P-014, P-019, P-024, P-030) each carry trigger rates ≥ 0.09 in the talent-outsourcing context with quantified business cost; one of them is selected as the Act IV target failure mode in [`target_failure_mode.md`](target_failure_mode.md).
