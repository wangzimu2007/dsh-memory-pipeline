#!/usr/bin/env python3
"""Explicit-memory bridge.

A user saying "记住" is a strong memory request.  This script runs the item
through the tiered validation pipeline and only returns a canonical record when
the output passes.  It does not write Hindsight itself; the caller writes the
returned record through the MCP memory service.
"""

import argparse
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import memory_pipeline as mp


def safety_check(text):
    lowered = text.lower()
    bad = [
        "sk-", "ghp_", "github_pat_", "aws_access_key", "aws_secret",
        "-----begin private key-----", "密码:", "密码：", "password:",
    ]
    hits = [b for b in bad if b in lowered]
    return not hits, hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--scope", default="global", choices=["global", "workspace"])
    ap.add_argument("--start", default="q4", choices=["q4", "9b", "27b", "strata", "cloud"])
    ap.add_argument("--config", default=str(BASE / "pipeline.config.json"))
    ap.add_argument("--out", default=str(BASE / "explicit_memory_record.json"))
    args = ap.parse_args()

    text = args.text.strip()
    if not text:
        raise SystemExit("empty memory")
    ok, hits = safety_check(text)
    if not ok:
        print(json.dumps({"accepted": False, "reason": "sensitive_text", "hits": hits}, ensure_ascii=False))
        return 2

    cfg = mp.load_config(args.config)
    start_index = cfg["tier_order"].index(args.start)
    # Use a structured extraction pass as the validation gate.  The canonical
    # memory text stays exactly what the user asked to remember.
    case = {
        "id": "explicit-" + str(int(time.time())),
        "task": "extraction",
        "evidence": [{"id": "s0", "path": ["user-explicit"], "text": text}],
    }
    result = mp.process_case(case, cfg, start_index)

    used_models = set()
    for attempt in result.get("attempts", []):
        tier_cfg = cfg["tiers"].get(attempt.get("tier"))
        if attempt.get("attempt") and tier_cfg and tier_cfg.get("kind") == "ollama":
            used_models.add(tier_cfg.get("model"))
    for model in sorted(used_models):
        mp.stop_ollama_model(model)

    record = {
        "accepted": bool(result.get("accepted")),
        "source": "explicit",
        "trust": "high",
        "priority": 100,
        "scope": args.scope,
        "text": text,
        "final_tier": result.get("final_tier"),
        "attempts": [
            {
                "tier": a.get("tier"),
                "attempt": a.get("attempt"),
                "ok": a.get("ok"),
                "errors": a.get("errors"),
                "decision": a.get("decision"),
            }
            for a in result.get("attempts", [])
        ],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    Path(args.out).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
