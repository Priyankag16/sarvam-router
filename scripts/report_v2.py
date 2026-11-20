"""
Results tables + Part 2 economics from the LIVE 75-prompt tuning-set run.

    python scripts/report_v2.py     -> results/tuning_v2/report.md

- Inputs: results/tuning_v2/{router,always_cheapest,always_frontier}.jsonl
  (live answers, tokens, cost, latency) and scores.jsonl from score_v2.py
  (code scores for the objective rubrics, rubric review for the rest).
- Bootstrap: resample the 75 prompts 2,000 times to get a 95% range for the
  router's saving vs frontier and for the difference in passes.
- Monthly cost uses the same method as report.py: each setup's split of
  tokens across models (failed attempts included) is applied to 50M input +
  10M output tokens at Sarvam's list prices. What-ifs: output scaled by
  measured reasoning, twice the hard traffic, and the intro price ending.
"""
import json
import pathlib
import random
import statistics
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from report import monthly, token_shares  # noqa: E402

RES = ROOT / "results/tuning_v2"
CONFIGS = ["always_cheapest", "always_frontier", "router"]
NAME = {"always_cheapest": "Always-cheapest (conversations)", "always_frontier": "Always-frontier (GLM-5.3)",
        "router": "Router"}
SHORT = {"always_cheapest": "Cheapest", "always_frontier": "Frontier", "router": "Router"}


def pct(xs, p):
    s = sorted(xs)
    return s[max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))] if s else 0


def main():
    cfg = yaml.safe_load(open(ROOT / "config/models.yaml", encoding="utf8"))
    fx = cfg["fx_inr_per_usd"]
    src = {json.loads(l)["id"]: json.loads(l) for l in open(ROOT / "data/tuning_v2.jsonl", encoding="utf8")}
    runs = {c: [json.loads(l) for l in open(RES / f"{c}.jsonl", encoding="utf8")] for c in CONFIGS}
    sc = {}
    for l in open(RES / "scores.jsonl", encoding="utf8"):
        x = json.loads(l)
        sc[(x["id"], x["config"])] = x
    ids = list(src)
    L = ["# Live results: 75-prompt tuning set, router vs baselines (2026-11-18)\n",
         "Live Sarvam API. Scoring: objective rubrics by script (25 prompts), the rest against the "
         "author's rubric with a written reason (50 prompts); pass = score >= the sheet's pass mark. Author's blind scores pending.\n",
         "## 1. Baselines vs router\n",
         "| Metric | " + " | ".join(NAME[c] for c in CONFIGS) + " |", "|---|---|---|---|"]

    def stat(c):
        rows = {r["id"]: r for r in runs[c]}
        lat = [r["latency_ms"] for r in runs[c] if r["latency_ms"] > 0]
        voice = [rows[i]["latency_ms"] for i in ids if src[i]["channel"] == "voice_live"]
        out = sum(r["out_tokens"] for r in runs[c])
        return {
            "pass": sum(sc[(i, c)]["passed"] for i in ids),
            "pct": statistics.mean(sc[(i, c)]["score"] / sc[(i, c)]["max_score"] for i in ids),
            "pass_hard": sum(sc[(i, c)]["passed"] for i in ids if src[i]["difficulty"] == "hard"),
            "pass_indic": sum(sc[(i, c)]["passed"] for i in ids if src[i]["lang"] != "en"),
            "pass_en": sum(sc[(i, c)]["passed"] for i in ids if src[i]["lang"] == "en"),
            "cost": sum(r["cost_inr"] for r in runs[c]),
            "p50": pct(lat, 50), "p95": pct(lat, 95), "voice_p95": pct(voice, 95),
            "rsn": sum(r.get("reasoning_tokens", 0) for r in runs[c]) / out if out else 0,
            "empty": sum(1 for r in runs[c] if not (r.get("answer") or "").strip() and not r["gave_up"]),
            "fallback": sum(r["fallback_fired"] for r in runs[c]),
        }
    S = {c: stat(c) for c in CONFIGS}
    n_hard = sum(src[i]["difficulty"] == "hard" for i in ids)
    n_indic = sum(src[i]["lang"] != "en" for i in ids)
    spec = [("Passed (of 75)", "pass", "{}"), ("Avg score, % of max", "pct", "{:.0%}"),
            (f"Passed: hard prompts (of {n_hard})", "pass_hard", "{}"),
            (f"Passed: Hindi/Punjabi/Hinglish (of {n_indic})", "pass_indic", "{}"),
            (f"Passed: English (of {75 - n_indic})", "pass_en", "{}"),
            ("Cost, 75 requests (₹)", "cost", "{:.2f}"),
            ("p50 latency (s)", "p50", None), ("p95 latency (s)", "p95", None),
            ("p95 latency, live voice (s)", "voice_p95", None),
            ("Reasoning share of output tokens", "rsn", "{:.0%}"),
            ("Blank answers (token budget spent reasoning)", "empty", "{}"),
            ("Requests where a fallback fired", "fallback", "{}")]
    for label, k, f in spec:
        vals = [(f"{S[c][k] / 1000:.1f}" if f is None else f.format(S[c][k])) for c in CONFIGS]
        L.append(f"| {label} | " + " | ".join(vals) + " |")

    # bootstrap
    rng = random.Random(7)
    R = {r["id"]: r for r in runs["router"]}
    F = {r["id"]: r for r in runs["always_frontier"]}
    sav, dp = [], []
    for _ in range(2000):
        s = [rng.choice(ids) for _ in ids]
        sav.append(1 - sum(R[i]["cost_inr"] for i in s) / sum(F[i]["cost_inr"] for i in s))
        dp.append(sum(sc[(i, "router")]["passed"] - sc[(i, "always_frontier")]["passed"] for i in s))
    save = 1 - S["router"]["cost"] / S["always_frontier"]["cost"]
    L.append(f"\nRouter vs always-frontier on these 75 prompts: **{save:.0%} cheaper** "
             f"(95% bootstrap range {pct(sav, 2.5):.0%}–{pct(sav, 97.5):.0%}); passes "
             f"{S['router']['pass']} vs {S['always_frontier']['pass']} "
             f"(difference {S['router']['pass'] - S['always_frontier']['pass']:+d}, range {pct(dp, 2.5):+d} to {pct(dp, 97.5):+d}).")

    # by task type
    cats = ["classification", "extraction", "drafting", "summary", "translation", "reasoning", "qa",
            "support_reply", "compliance"]
    L += ["\n## 2. Passes by task type\n", "| Task (n) | " + " | ".join(SHORT[c] for c in CONFIGS) + " |",
          "|---|---|---|---|"]
    for cat in cats:
        ii = [i for i in ids if src[i]["category"] == cat]
        vals = [sum(sc[(i, c)]["passed"] for i in ii) for c in CONFIGS]
        best = max(vals)
        L.append(f"| {cat} ({len(ii)}) | " + " | ".join(f"**{v}**" if v == best else str(v) for v in vals) + " |")
    L += ["\n## 3. Passes by language\n", "| Language (n) | " + " | ".join(SHORT[c] for c in CONFIGS) + " |",
          "|---|---|---|---|"]
    for lg in ["en", "hi", "pa", "hinglish", "rom_pa"]:
        ii = [i for i in ids if src[i]["lang"] == lg]
        L.append(f"| {lg} ({len(ii)}) | " + " | ".join(str(sum(sc[(i, c)]["passed"] for i in ii)) for c in CONFIGS) + " |")

    # routing
    from collections import Counter
    rules = Counter(r["rule_id"] for r in runs["router"])
    models = Counter(r["model"] or "template (no model)" for r in runs["router"])
    hard_ids = [i for i in ids if src[i]["difficulty"] == "hard"]
    # under-routed: a hard prompt that didn't land on a hard rule;
    # over-routed: an easy prompt that ended up on the expensive GLM-5.3
    under = [i for i in hard_ids if R[i]["rule_id"] not in ("R3-hard-en", "R3-hard-indic", "R3c-compliance", "R2-voice-hard")]
    over = [i for i in ids if src[i]["difficulty"] == "easy" and R[i]["model"] == "glm-5.3"]
    hr_want = [i for i in ids if src[i]["expected_human_review"]]
    hr_got = [i for i in ids if R[i].get("human_review")]
    L += ["\n## 4. Where the router sent traffic\n",
          "| Rule | Requests |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(rules.items())]
    L += ["", "| Final model | Requests |", "|---|---|"] + [f"| {k} | {v} |" for k, v in models.most_common()]
    L.append(f"\nUnder-routed (hard prompt not on a hard rule): {under or 'none'}. "
             f"Over-routed (easy prompt answered by GLM-5.3): {over or 'none'}.")
    L.append(f"Human review: sheet expects {len(hr_want)}; router flagged {len(hr_got)}; "
             f"correct flags {len(set(hr_want) & set(hr_got))}, missed {sorted(set(hr_want) - set(hr_got))}, "
             f"false {sorted(set(hr_got) - set(hr_want))}.")

    # economics
    fr = runs["always_frontier"]
    head = {c: monthly(runs[c], fr, cfg) for c in CONFIGS}
    adj = {c: monthly(runs[c], fr, cfg, scale_out=True) for c in CONFIGS}
    hard2 = {c: monthly(runs[c], fr, cfg, weight=lambda r: 2.0 if r["difficulty"] == "hard" else 1.0) for c in CONFIGS}
    post = {m: (v["in_inr_per_m"], v["out_inr_per_m"]) for m, v in cfg["models"].items()}
    pi = cfg["post_intro_sarvam_price"]
    for m in ("sarvam-105b", "sarvam-105b-conversations"):
        post[m] = (pi["in_inr_per_m"], pi["out_inr_per_m"])
    postp = {c: monthly(runs[c], fr, cfg, prices=post) for c in CONFIGS}
    L += ["\n## 5. Part 2 economics: 50M input + 10M output tokens / month (from the live token mix)\n",
          "| Configuration | Monthly cost | US$ | Saving vs frontier |", "|---|---|---|---|"]
    for c in CONFIGS:
        L.append(f"| {NAME[c]} | ₹{head[c]:,.0f} | ${head[c] / fx:,.0f} | {1 - head[c] / head['always_frontier']:.0%} |")
    L.append(f"\n**Four numbers:** cheapest ₹{head['always_cheapest']:,.0f}, frontier ₹{head['always_frontier']:,.0f}, "
             f"router ₹{head['router']:,.0f}; router saves **{1 - head['router'] / head['always_frontier']:.0%}** vs frontier.\n")
    L += ["| Sensitivity | Cheapest | Frontier | Router | Router saving |", "|---|---|---|---|---|"]
    for label, d in (("Headline: fixed 10M output tokens", head),
                     ("Output scales with each config's measured output (incl. reasoning)", adj),
                     ("Hard traffic doubled", hard2),
                     ("Sarvam intro price ends (assumed ₹13.5 / ₹45 per 1M)", postp)):
        L.append(f"| {label} | ₹{d['always_cheapest']:,.0f} | ₹{d['always_frontier']:,.0f} | ₹{d['router']:,.0f} | "
                 f"{1 - d['router'] / d['always_frontier']:.0%} |")
    tin, tout = token_shares(runs["router"])
    L.append("\nRouter token mix (share of input / output tokens): " + ", ".join(
        f"{m} {tin[m] / sum(tin.values()):.0%} / {tout.get(m, 0) / sum(tout.values()):.0%}" for m in sorted(tin)))
    L.append(f"\nPrices: Sarvam list prices (₹ per 1M, ex-GST) as of {cfg['price_date']}; US$ at ₹{fx}/$.")
    text = "\n".join(L)
    (RES / "report.md").write_text(text, encoding="utf8")
    print(text)


if __name__ == "__main__":
    main()
