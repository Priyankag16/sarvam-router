"""
Route one prompt from the command line: see the decision, and (optionally) the answer.

    python route.py "Classify the intent: mera card block karo" --dry-run
    python route.py "₹2,00,000 ka loan 11% pe 36 mahine, EMI kitni?"
    python route.py "..." --tenant agri_gov --channel voice_live

--dry-run only shows what the router would do (rule, reason, fallback ladder,
language, cues) without calling a model. It's free and instant, so it's handy
while editing the cue lists. Without it, the prompt is sent to the Sarvam API
(needs SARVAM_API_KEY in .env) and the answer, model, tokens, cost and
latency are printed.
"""
import argparse
import json
import pathlib

from dotenv import load_dotenv

from router.call import run_ladder
from router.classify import classify, mask_pii
from router.rules import needs_human, route
from run_eval import load_cfg

ROOT = pathlib.Path(__file__).parent


def main():
    ap = argparse.ArgumentParser(description="Route one prompt through the Sarvam router.")
    ap.add_argument("prompt")
    ap.add_argument("--tenant", default="bfsi", help="bfsi | telecom | agri_gov (config/tenants/*.yaml)")
    ap.add_argument("--channel", default="text", choices=["text", "voice_live", "batch"])
    ap.add_argument("--dry-run", action="store_true", help="show the decision only; no API call")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    cfg, tenants = load_cfg()
    tenant = tenants[args.tenant]
    masked, n_masked = mask_pii(args.prompt)     # hide card/OTP/Aadhaar first
    c = classify(masked)
    req = {"id": "cli", "tenant": args.tenant, "channel": args.channel, "category": "cli", "prompt": masked}
    d = route(req, c, tenant)
    out = {"rule": d.rule_id, "reason": d.reason, "language": c.language, "pii_masked": n_masked,
           "ladder": [f"{s.model}" + ("" if s.effort == "default" else f" ({s.effort})") for s in d.ladder],
           "cues": {"hard": c.hard_cues, "simple": c.simple_cues, "language_task": c.language_task_cues,
                    "compliance": c.compliance_cues},
           "router_overhead_ms": round(c.overhead_ms, 3)}
    if d.template is not None:                   # R1: canned reply, no model needed
        out["answer"] = d.template
        out["model"] = None
    elif not args.dry_run:
        req = {**req, "_instruction": d.instruction, "_temperature": d.temperature}
        res = run_ladder(req, masked, d.ladder, cfg, mock=False)
        out.update({"model": res["model"], "answer": (res["final"] or {}).get("text") if res["final"] else None,
                    "attempts": [f"{a['model']}:{a['status']}" for a in res["attempts"]],
                    "tokens_in": sum(a["in_tokens"] for a in res["attempts"]),
                    "tokens_out": sum(a["out_tokens"] for a in res["attempts"]),
                    "reasoning_tokens": sum(a.get("reasoning_tokens", 0) for a in res["attempts"]),
                    "cost_inr": round(res["cost_inr"], 5), "latency_ms": round(res["latency_s"] * 1000)})
    out["human_review"] = needs_human(req, masked, out.get("answer"), d.rule_id, tenant)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print(f"rule     : {out['rule']}  ({out['reason']})")
    print(f"language : {out['language']}   PII masked: {n_masked}   router overhead: {out['router_overhead_ms']} ms")
    print(f"ladder   : {' > '.join(out['ladder']) or 'none (rule reply)'}")
    if "answer" in out:
        if out.get("model"):
            print(f"model    : {out['model']}   attempts: {', '.join(out['attempts'])}")
            print(f"cost     : ₹{out['cost_inr']}   latency: {out['latency_ms']} ms   tokens: "
                  f"{out['tokens_in']} in / {out['tokens_out']} out ({out['reasoning_tokens']} reasoning)")
        print(f"review   : {out['human_review']}")
        print(f"answer   :\n{out['answer']}")


if __name__ == "__main__":
    main()
