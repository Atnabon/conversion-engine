"""τ²-Bench harness wrapper.

Pinned settings are read from ../configs/pinned_models.yaml.
Every run writes to:
    - eval/trace_log.jsonl (one JSON object per task trajectory)
    - eval/score_log.json (aggregated per-run summary with 95% CI)
    - Langfuse cloud (per-trace cost + latency attribution)

Usage:
    python tau2_harness.py --domain retail --trials 5 --slice dev
    python tau2_harness.py --domain retail --trials 1 --slice held_out --tier eval
"""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="retail")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--slice", choices=["dev", "held_out"], default="dev")
    parser.add_argument("--tier", choices=["dev", "eval"], default="dev")
    args = parser.parse_args()
    # Load pinned model config, run tasks, compute pass@1 with 95% CI,
    # write trace_log.jsonl + score_log.json, flush to Langfuse.
    raise NotImplementedError(
        "Skeleton — real implementation wires tau2-bench pinned runner."
    )


if __name__ == "__main__":
    main()
