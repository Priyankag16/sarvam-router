"""
Run the held-out test set through three configurations and log every request.

    python run_eval.py --mock            # no API key: simulated, labelled mock
    python run_eval.py                   # real calls (needs SARVAM_API_KEY in .env)
    python run_eval.py --data data/dev.jsonl --out results/dev   # tuning set

All three setups get the same prompts:
  always_cheapest : every request -> the cheapest model (see baselines in config/models.yaml)
  always_frontier : every request -> glm-5.3 (what most customers do today)
  router          : classify -> rules -> ladder -> judge
The baselines get none of the router's extras (no junk filter, no PII masking,
no ladder, just the same one retry), so the difference shows what routing
itself adds. The router's classify time is added to its latency.
Human review (R6) is only flagged; it adds no cost or time to any setup, so
the cost comparison stays fair.

Output: results/<config>.jsonl, one row per request with every logged field.
"""
import argparse
import json
import os
import pathlib

import yaml

from router.call import run_ladder
from router.classify import classify, mask_pii
from router.judge import score
from router.rules import Step, needs_human, route

ROOT = pathlib.Path(__file__).parent


def load_cfg():
    """Load the model config and every tenant file (keyed by file name)."""
    cfg = yaml.safe_load(open(ROOT / "config/models.yaml", encoding="utf8"))
    tenants = {}
    for f in (ROOT / "config/tenants").glob("*.yaml"):
        t = yaml.safe_load(open(f, encoding="utf8"))
        tenants[f.stem] = t
    return cfg, tenants


def run_one(req, config, cfg, tenant, mock):
    """Run one prompt through one setup and return its log row."""
    prompt = req["prompt"]
    row = {"id": req["id"], "config": config, "tenant": req["tenant"], "channel": req["channel"],
           "lang": req["lang"], "difficulty": req["difficulty"], "hardest": req.get("hardest", False),
           "category": req["category"], "mode": "mock" if mock else "real"}

    if config == "router":
        masked, n_masked = mask_pii(prompt)          # before any model sees it
        c = classify(masked)
        d = route(req, c, tenant)
        row.update({"rule_id": d.rule_id, "reason": d.reason, "detected_lang": c.language,
                    "pii_masked": n_masked, "router_overhead_ms": round(c.overhead_ms, 3),
                    "router_tokens": c.router_tokens})
        if d.template is not None:                    # R1: no model call
            res = {"final": None, "model": None, "effort": None, "attempts": [], "cost_inr": 0.0,
                   "latency_s": 0.0, "gave_up": False, "template": d.template}
        else:
            req = {**req, "_instruction": d.instruction, "_temperature": d.temperature}
            res = run_ladder(req, masked, d.ladder, cfg, mock)
        # R6: decided from the answer, once it's written (router/review.py).
        # Labels (R4), canned replies (R1) and refusals never go for review.
        answer_text = (res["final"] or {}).get("text") if res.get("final") else None
        hr = needs_human(req, masked, answer_text, d.rule_id, tenant)
        row["human_review"] = hr["action"] if hr else None
        row["human_review_rule"] = hr["rule"] if hr else None
        row["human_review_reason"] = hr["reason"] if hr else None
        row["holding_phrase"] = d.holding_phrase is not None
        overhead_s = c.overhead_ms / 1000
    else:
        # "fixed:<model>" = send everything to that one model (model comparison runs)
        model = config.split(":", 1)[1] if config.startswith("fixed:") else cfg["baselines"][config]
        res = run_ladder(req, prompt, [Step(model)], cfg, mock)
        row.update({"rule_id": f"BASE-{config}", "reason": "baseline: fixed model", "human_review": None})
        overhead_s = 0.0

    q = score(req, res, mock, cfg)
    row.update({
        "model": res["model"], "effort": res["effort"],
        "in_tokens": sum(a["in_tokens"] for a in res["attempts"]),
        "out_tokens": sum(a["out_tokens"] for a in res["attempts"]),
        "cost_inr": round(res["cost_inr"], 6),
        "latency_ms": round((res["latency_s"] + overhead_s) * 1000, 1),
        "attempts": res["attempts"],
        "reasoning_tokens": sum(a.get("reasoning_tokens", 0) for a in res["attempts"]),
        "answer": (res["final"] or {}).get("text") if res.get("final") else res.get("template"),
        "fallback_fired": len(res["attempts"]) > 1,
        "gave_up": res["gave_up"],
        "quality": q["quality"], "judge": q["judge"], "checks_failed": q["checks_failed"],
    })
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="simulate calls (no API key)")
    ap.add_argument("--data", default="data/test.jsonl")
    ap.add_argument("--out", default="results")
    ap.add_argument("--configs", default="always_cheapest,always_frontier,router",
                    help="comma-separated subset to run, e.g. router")
    ap.add_argument("--timeout", type=float, default=None,
                    help="override every model's timeout (seconds) for fair model comparisons")
    ap.add_argument("--judge", choices=["llm", "human"], default="llm",
                    help="human = leave quality blank and score by hand later")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    if not args.mock and not os.environ.get("SARVAM_API_KEY"):
        raise SystemExit("No SARVAM_API_KEY found. Add it to .env or run with --mock.")

    cfg, tenants = load_cfg()
    cfg["_judge"] = args.judge
    if args.timeout:
        for m in cfg["models"].values():
            m["timeout_s"] = args.timeout
    reqs = [json.loads(l) for l in open(ROOT / args.data, encoding="utf8") if l.strip()]
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    for config in args.configs.split(","):
        rows = [run_one(r, config, cfg, tenants[r["tenant"]], args.mock) for r in reqs]
        with open(out / f"{config.replace(':', '_')}.jsonl", "w", encoding="utf8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{config:16s} {len(rows)} requests  cost ₹{sum(r['cost_inr'] for r in rows):.4f}", flush=True)


if __name__ == "__main__":
    main()
