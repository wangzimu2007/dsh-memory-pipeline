#!/usr/bin/env python3
"""Tiered local/cloud memory pipeline.

Default route:
  q4 -> 9b -> 27b -> strata -> cloud

`--start` selects the first tier. Tiers before it are skipped entirely.
Validation is deterministic; a tier is only accepted after its JSON output
passes the task schema and evidence checks. Hindsight is not touched.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE / "pipeline.config.json"


def load_config(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_json(raw):
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def get_free_vram_mb():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, text=True, timeout=10,
        )
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def get_ollama_exe():
    return os.environ.get(
        "OLLAMA_EXE",
        shutil.which("ollama") or "ollama",
    )


def get_loaded_ollama_models():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {m.get("name") or m.get("model") for m in data.get("models", []) if isinstance(m, dict)}
    except Exception:
        return set()


def stop_ollama_model(model):
    if not model:
        return False
    try:
        subprocess.run(
            [get_ollama_exe(), "stop", model],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
        )
        print(f"UNLOAD {model}")
        return True
    except Exception as exc:
        print(f"UNLOAD_FAIL {model}: {exc}")
        return False


def wait_for_free_vram(need_mb, cfg, tier):
    timeout = int(cfg.get("vram_wait_timeout_sec", 1800))
    poll = max(2, int(cfg.get("vram_poll_sec", 10)))
    start = time.time()
    while True:
        free = get_free_vram_mb()
        if free is None or free >= need_mb:
            return True, free
        elapsed = int(time.time() - start)
        if elapsed >= timeout:
            return False, free
        print(f"WAIT_VRAM tier={tier} free={free}MB need={need_mb}MB elapsed={elapsed}s")
        time.sleep(poll)


def call_ollama(cfg, system_prompt, user_payload, timeout=180):
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "stream": False,
        "think": False,
        "options": {
            "num_ctx": cfg.get("num_ctx", 16384),
            "temperature": 0.0,
            "top_k": 20,
            "top_p": 0.95,
            "presence_penalty": 0.0,
        },
    }
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/api/chat",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    elapsed = time.time() - t0
    content = ((res.get("message") or {}).get("content") or "").strip()
    eval_count = float(res.get("eval_count") or 0)
    eval_duration = float(res.get("eval_duration") or 0)
    tps = eval_count / (eval_duration / 1e9) if eval_duration > 0 else 0.0
    return content, elapsed, tps


def call_openai_compatible(cfg, system_prompt, user_payload, timeout=180):
    key = os.environ.get(cfg.get("api_key_env", ""), "")
    if not key and cfg.get("require_key"):
        raise RuntimeError(f"missing env {cfg.get('api_key_env')}")
    if not key:
        key = "local"
    base_url = os.environ.get(cfg.get("base_url_env", ""), cfg["base_url"])
    model = os.environ.get(cfg.get("model_env", ""), cfg["model"])
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0.0,
        "stream": False,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    elapsed = time.time() - t0
    content = (((res.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    usage = res.get("usage") or {}
    return content, elapsed, 0.0, usage


def validate_extraction(raw, valid_ids):
    try:
        data = parse_json(raw)
    except Exception as exc:
        return False, [f"invalid_json: {exc}"], ""
    if not isinstance(data, dict) or not isinstance(data.get("facts"), list):
        return False, ["missing facts list"], ""
    if not data["facts"]:
        return False, ["empty facts"], ""
    errs = []
    required = {"text", "type", "occurred_start", "occurred_end", "where", "entities", "evidence"}
    for i, f in enumerate(data["facts"]):
        if not isinstance(f, dict):
            errs.append(f"fact[{i}] not object")
            continue
        if required - set(f):
            errs.append(f"fact[{i}] missing {sorted(required - set(f))}")
        if f.get("type") not in {"world", "experience", "observation"}:
            errs.append(f"fact[{i}] bad type {f.get('type')!r}")
        ev = f.get("evidence")
        if not isinstance(ev, list) or not (1 <= len(ev) <= 4):
            errs.append(f"fact[{i}] bad evidence {ev!r}")
        elif not set(ev).issubset(valid_ids):
            errs.append(f"fact[{i}] hallucinated evidence {sorted(set(ev) - valid_ids)}")
        if not str(f.get("text") or "").strip():
            errs.append(f"fact[{i}] empty text")
    return not errs, errs, ""


def validate_admission(raw, valid_ids, allowed):
    try:
        data = parse_json(raw)
    except Exception as exc:
        return False, [f"invalid_json: {exc}"], ""
    if not isinstance(data, dict) or not isinstance(data.get("0"), dict):
        return False, ["missing slot 0"], ""
    slot = data["0"]
    errs = []
    for k in ("decision", "evidence", "replacement"):
        if k not in slot:
            errs.append(f"missing {k}")
    dec = slot.get("decision")
    if dec not in {"pass", "revise", "drop", "hold"}:
        errs.append(f"bad decision {dec!r}")
    elif dec not in allowed:
        errs.append(f"decision {dec!r} not in {allowed}")
    ev = slot.get("evidence")
    if not isinstance(ev, list) or not set(ev).issubset(valid_ids):
        errs.append(f"bad evidence {ev!r}")
    if dec == "revise" and not str(slot.get("replacement") or "").strip():
        errs.append("revise needs replacement")
    if dec in {"drop", "hold"} and str(slot.get("replacement") or "").strip():
        errs.append("drop/hold should have empty replacement")
    if dec in {"pass", "revise"} and not ev:
        errs.append("pass/revise needs evidence")
    return not errs, errs, (dec or "")


def tier_available(name, cfg, global_cfg, wait=True):
    if name == "cloud":
        env = cfg.get("api_key_env")
        if env and not os.environ.get(env):
            return False, f"missing env {env}"
    need = cfg.get("min_free_vram_mb")
    if need:
        # If this Ollama model is already resident, its own VRAM is already
        # accounted for; no need to wait for extra free memory.
        model = cfg.get("model")
        if cfg.get("kind") == "ollama" and model in get_loaded_ollama_models():
            return True, ""
        if wait:
            ok, free = wait_for_free_vram(need, global_cfg, name)
            if not ok:
                return False, f"VRAM timeout: free {free}MB < {need}MB"
        else:
            free = get_free_vram_mb()
            if free is not None and free < need:
                return False, f"free VRAM {free}MB < {need}MB"
    return True, ""


def call_tier(name, cfg, system_prompt, user_payload):
    if cfg.get("kind") == "ollama":
        raw, elapsed, tps = call_ollama(cfg, system_prompt, user_payload)
        return raw, elapsed, tps, {}
    raw, elapsed, tps, usage = call_openai_compatible(cfg, system_prompt, user_payload)
    return raw, elapsed, tps, usage


def build_validation(task, case, raw):
    valid_ids = {s["id"] for s in case["evidence"]}
    if task == "extraction":
        ok, errs, decision = validate_extraction(raw, valid_ids)
    else:
        ok, errs, decision = validate_admission(raw, valid_ids, case.get("allowed") or [])
    return ok, errs, decision


def process_case(case, cfg, start_index):
    task = case["task"]
    prompts_dir = Path(cfg["prompts_dir"])
    if task == "extraction":
        system_prompt = (prompts_dir / "prompts" / "fact_extraction_system.txt").read_text(encoding="utf-8")
        payload = {"bank": "hermes", "document_id": case.get("id", "pipeline"), "evidence": case["evidence"]}
    else:
        system_prompt = (prompts_dir / "prompts" / "fact_admission_system.txt").read_text(encoding="utf-8")
        payload = {"evidence": case["evidence"], "facts": {"0": case["fact"]}}

    order = cfg["tier_order"][start_index:]
    attempts = []
    for tier in order:
        tier_cfg = cfg["tiers"].get(tier)
        if not tier_cfg:
            attempts.append({"tier": tier, "status": "missing_config"})
            continue
        available, reason = tier_available(tier, tier_cfg, cfg)
        if not available:
            attempts.append({"tier": tier, "status": "skipped", "reason": reason})
            continue

        max_attempts = int(tier_cfg.get("max_attempts", 1))
        previous_raw = ""
        previous_errors = []
        tier_failed = False
        for attempt in range(1, max_attempts + 1):
            request_payload = payload
            if attempt > 1:
                request_payload = dict(payload)
                request_payload["_previous_output"] = previous_raw
                request_payload["_validation_errors"] = previous_errors
            try:
                raw, elapsed, tps, usage = call_tier(tier, tier_cfg, system_prompt, request_payload)
                ok, errors, decision = build_validation(task, case, raw)
            except Exception as exc:
                raw, elapsed, tps, usage = "", 0.0, 0.0, {}
                ok, errors, decision = False, [f"runtime: {exc}"], ""
            attempts.append({
                "tier": tier,
                "attempt": attempt,
                "elapsed": round(elapsed, 3),
                "tps": round(tps, 1),
                "ok": ok,
                "errors": errors,
                "decision": decision,
                "raw": raw,
                "usage": usage,
            })
            if ok:
                return {
                    "id": case.get("id"),
                    "task": task,
                    "accepted": True,
                    "final_tier": tier,
                    "attempts": attempts,
                    "final_decision": decision,
                    "final_raw": raw,
                }
            tier_failed = True
            previous_raw = raw
            previous_errors = errors

        # Free the failed tier before trying a larger model.  This is the
        # explicit "9B failed -> unload -> 27B" behavior.
        if tier_failed and cfg.get("unload_on_failure", True) and tier_cfg.get("kind") == "ollama":
            stop_ollama_model(tier_cfg.get("model"))

    return {
        "id": case.get("id"),
        "task": task,
        "accepted": False,
        "final_tier": None,
        "attempts": attempts,
        "final_decision": "",
        "final_raw": "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--start", default="q4", choices=["q4", "9b", "27b", "strata", "cloud"])
    ap.add_argument("--out", default=str(BASE / "pipeline_results.json"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.start not in cfg["tier_order"]:
        raise SystemExit(f"unknown start tier: {args.start}")
    start_index = cfg["tier_order"].index(args.start)
    order = cfg["tier_order"][start_index:]
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[:args.limit]

    print(f"START={args.start} ROUTE={' -> '.join(order)} CASES={len(cases)}")
    if args.dry_run:
        for c in cases:
            print(c.get("id"), c.get("task"))
        return

    results = []
    tier_accepts = {}
    tier_skips = {}
    for idx, case in enumerate(cases, 1):
        result = process_case(case, cfg, start_index)
        results.append(result)
        for a in result["attempts"]:
            if a.get("ok"):
                tier_accepts[a["tier"]] = tier_accepts.get(a["tier"], 0) + 1
            elif a.get("status") == "skipped":
                tier_skips[a["tier"]] = tier_skips.get(a["tier"], 0) + 1
        status = "OK " + result["final_tier"] if result["accepted"] else "HUMAN"
        print(f"[{idx:03d}/{len(cases)}] {case.get('id'):<44} {status}")
        if not result["accepted"]:
            failed = [a for a in result["attempts"] if not a.get("ok") and a.get("status") != "skipped"]
            errs = failed[-1].get("errors", []) if failed else []
            print("        -> " + ("; ".join(errs)[:300] if errs else "all remaining tiers skipped/unavailable"))

    accepted = sum(1 for r in results if r["accepted"])

    # Models are intentionally not kept resident after the batch.  Only models
    # that this run actually called are stopped; Strata and cloud are services.
    used_models = set()
    for r in results:
        for a in r["attempts"]:
            tier_cfg = cfg["tiers"].get(a.get("tier"))
            if a.get("attempt") and tier_cfg and tier_cfg.get("kind") == "ollama":
                used_models.add(tier_cfg.get("model"))
    if cfg.get("unload_on_finish", True):
        for model in sorted(used_models):
            stop_ollama_model(model)

    print("=" * 72)
    print(f"ACCEPTED={accepted}/{len(results)}")
    print("TIER_ACCEPTS=" + json.dumps(tier_accepts, ensure_ascii=False))
    print("TIER_SKIPS=" + json.dumps(tier_skips, ensure_ascii=False))
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OUT=" + args.out)


if __name__ == "__main__":
    main()
