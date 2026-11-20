"""
Print the router's and both baselines' answers side by side, for judging.

    python scripts/show_answers.py u11 u12 ...   [--full]

Handy while scoring by hand: shows the prompt, reference answer and rubric,
then each setup's model, status, tokens, latency and answer.
Long answers are cut down to start ... end unless --full is given.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIGS = ["router", "always_cheapest", "always_frontier"]


def main(ids, full=False):
    src = {json.loads(l)["id"]: json.loads(l) for l in open(ROOT / "data/tuning_v2.jsonl", encoding="utf8")}
    runs = {c: {json.loads(l)["id"]: json.loads(l)
                for l in open(ROOT / f"results/tuning_v2/{c}.jsonl", encoding="utf8")} for c in CONFIGS}
    for i in ids:
        s = src[i]
        p = s["prompt"] if len(s["prompt"]) < 400 else s["prompt"][:200] + " … " + s["prompt"][-150:]
        print(f"\n===== {i} [{s['category']}/{s['lang']}/{s['channel']}] max {s['max_score']:g} pass {s['pass_mark']:g}")
        print("  PROMPT:", p.replace("\n", " ⏎ "))
        print("  REF   :", s["reference"])
        print("  RUBRIC:", s["rubric"])
        for c in CONFIGS:
            r = runs[c][i]
            a = (r.get("answer") or "(EMPTY)").strip().replace("\n", " ⏎ ")
            if not full and len(a) > 520:
                a = a[:300] + " … " + a[-200:]
            att = " > ".join(f"{x['model']}:{x['status']}" for x in r["attempts"]) or "template"
            print(f"  --[{c}] {r.get('rule_id', '')} {att} rsn={r.get('reasoning_tokens', 0)} "
                  f"{r['latency_ms'] / 1000:.1f}s: {a}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args, full="--full" in sys.argv)
