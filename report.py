"""
Turn results/*.jsonl into the numbers the README quotes.

    python report.py            -> writes results/report.md and results/cost_quality.svg

What's in the report:
1. Baseline table: total cost, cost per request, p50/p95 latency, average
   quality, quality on hard prompts and the 4 hardest, English vs Indic,
   and how often a fallback fired. With 40 requests, p95 is basically the
   2nd-worst value, so treat it as rough.
2. Bootstrap ranges: pick 40 prompts at random (with repeats) 2,000 times and
   recompute the router's saving and quality difference each time. The
   middle 95% of those is the range shown. With only 40 prompts it's wide.
3. Route mix: which rule and model handled each request.
4. Monthly cost at 50M input + 10M output tokens:
   - Each setup's split of tokens across models comes from the test run
     (weighted by tokens, not by number of requests).
   - Input is 50M, adjusted for what the router actually sends: junk/attack
     never reach a model (fewer tokens) and retries resend the prompt (more).
   - Output is a flat 10M for every setup in the headline numbers. A second
     view scales output by what each setup really produced, since reasoning
     tokens are billed as output.
   - What-ifs: twice as much hard traffic; Sarvam's intro price ending.
"""
import json
import pathlib
import random
import statistics

import yaml

ROOT = pathlib.Path(__file__).parent
RES = ROOT / "results"
CONFIGS = ["always_cheapest", "always_frontier", "router"]
IN_M, OUT_M = 50_000_000, 10_000_000
# prompts where a timeout / bad JSON is forced on purpose to test the ladder
INJECTED = {json.loads(l)["id"] for l in open(ROOT / "data/test.jsonl", encoding="utf8")
            if l.strip() and json.loads(l).get("inject")}


def load(name):
    return [json.loads(l) for l in open(RES / f"{name}.jsonl", encoding="utf8")]


def pct(vals, p):
    """Percentile using the nearest-rank method (always returns a real value)."""
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))   # nearest rank
    return s[k]


def mean(xs):
    return statistics.mean(xs) if xs else float("nan")


def summarise(rows):
    model_rows = [r for r in rows if r["latency_ms"] > 0]          # exclude zero-cost templates from latency
    return {
        "cost": sum(r["cost_inr"] for r in rows),
        "cost_per_req": sum(r["cost_inr"] for r in rows) / len(rows),
        "p50": pct([r["latency_ms"] for r in model_rows], 50),
        "p95": pct([r["latency_ms"] for r in model_rows], 95),
        "q": mean([r["quality"] for r in rows]),
        # baselines have no fallback ladder, so injected faults hit them harder;
        # this row removes those prompts to compare model quality alone
        "q_clean": mean([r["quality"] for r in rows if r["id"] not in INJECTED]),
        "q_hard": mean([r["quality"] for r in rows if r["difficulty"] == "hard"]),
        "q_hardest": mean([r["quality"] for r in rows if r["hardest"]]),
        "q_en": mean([r["quality"] for r in rows if r["lang"] == "en" and r["category"] not in ("junk", "attack")]),
        "q_indic": mean([r["quality"] for r in rows if r["lang"] != "en"]),
        "q_voice_p95": pct([r["latency_ms"] for r in rows if r["channel"] == "voice_live"] or [0], 95),
        "fallback": sum(r["fallback_fired"] for r in rows) / len(rows),
        "gave_up": sum(r["gave_up"] for r in rows),
    }


def bootstrap(router, frontier, n=2000, seed=7):
    """95% ranges for the cost saving and quality difference vs frontier."""
    rng = random.Random(seed)
    idx = range(len(router))
    sav, dq = [], []
    for _ in range(n):
        s = [rng.choice(idx) for _ in idx]
        cr = sum(router[i]["cost_inr"] for i in s)
        cf = sum(frontier[i]["cost_inr"] for i in s)
        sav.append(1 - cr / cf)
        dq.append(mean([router[i]["quality"] for i in s]) - mean([frontier[i]["quality"] for i in s]))
    return (pct(sav, 2.5), pct(sav, 97.5)), (pct(dq, 2.5), pct(dq, 97.5))


def token_shares(rows, weight=lambda r: 1.0):
    """Input and output tokens per model, counting every attempt (failed ones too)."""
    tin, tout = {}, {}
    for r in rows:
        w = weight(r)
        for a in r["attempts"]:
            tin[a["model"]] = tin.get(a["model"], 0) + a["in_tokens"] * w
            tout[a["model"]] = tout.get(a["model"], 0) + a["out_tokens"] * w
    return tin, tout


def monthly(rows, frontier_rows, cfg, weight=lambda r: 1.0, prices=None, scale_out=False):
    """Monthly ₹ cost for 50M in / 10M out, using this setup's token mix.
    The frontier run is the reference: its first attempts give the input size
    of sending every prompt once (base_in), and its output is today's output
    volume (frontier_out)."""
    prices = prices or {m: (v["in_inr_per_m"], v["out_inr_per_m"]) for m, v in cfg["models"].items()}
    base_in = sum(r["attempts"][0]["in_tokens"] * weight(r) for r in frontier_rows)
    frontier_out = sum(a["out_tokens"] * weight(r) for r in frontier_rows for a in r["attempts"])
    tin, tout = token_shares(rows, weight)
    sin, sout = sum(tin.values()), sum(tout.values())
    in_vol = IN_M * sin / base_in                                  # retries add, R1 removes
    out_vol = OUT_M * (sout / frontier_out if scale_out else 1.0)
    c = sum(in_vol * tin[m] / sin * prices[m][0] / 1e6 for m in tin if sin)
    c += sum(out_vol * tout[m] / sout * prices[m][1] / 1e6 for m in tout if sout)
    return c


def svg_chart(points):
    """Small cost-vs-quality scatter plot written as plain SVG."""
    W, H, pad = 520, 320, 60
    xs = [p[1] for p in points]
    xmax = max(xs) * 1.15
    qmin, qmax = 3.0, 5.0
    def X(v): return pad + v / xmax * (W - 2 * pad)
    def Y(q): return H - pad - (q - qmin) / (qmax - qmin) * (H - 2 * pad)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif" font-size="12">',
           f'<rect width="{W}" height="{H}" fill="white"/>',
           f'<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="#555"/>',
           f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{H-pad}" stroke="#555"/>',
           f'<text x="{W/2}" y="{H-20}" text-anchor="middle">Cost for 40 test requests (₹)</text>',
           f'<text x="18" y="{H/2}" transform="rotate(-90 18 {H/2})" text-anchor="middle">Mean quality (1-5)</text>']
    for q in (3.0, 3.5, 4.0, 4.5, 5.0):
        out.append(f'<text x="{pad-8}" y="{Y(q)+4}" text-anchor="end">{q}</text>')
    for v in (0, xmax / 2, xmax):
        out.append(f'<text x="{X(v)}" y="{H-pad+16}" text-anchor="middle">{v:.1f}</text>')
    colors = {"always_cheapest": "#2a7", "always_frontier": "#c44", "router": "#45c"}
    for name, cost, q in points:
        out.append(f'<circle cx="{X(cost)}" cy="{Y(q)}" r="7" fill="{colors[name]}"/>')
        out.append(f'<text x="{X(cost)+10}" y="{Y(q)-8}">{name}</text>')
    out.append(f'<text x="{W/2}" y="20" text-anchor="middle" font-weight="bold">Cost vs quality (MOCK run)</text></svg>')
    return "\n".join(out)


def main():
    cfg = yaml.safe_load(open(ROOT / "config/models.yaml", encoding="utf8"))
    fx = cfg["fx_inr_per_usd"]
    data = {c: load(c) for c in CONFIGS}
    mode = data["router"][0]["mode"]
    S = {c: summarise(rows) for c, rows in data.items()}
    L = []
    L.append(f"# Results ({mode.upper()} run, {len(data['router'])} held-out prompts)\n")
    if mode == "mock":
        L.append("> **MOCK RUN.** Latency, quality and failures are simulated from the stated assumptions in "
                 "`router/call.py`. Token counts are estimates; prices are real Sarvam list prices. Rerun with an "
                 "API key before quoting these as measurements.\n")

    L.append("## 1. Baselines vs router\n")
    L.append("| Metric | Always-cheapest (105B) | Always-frontier (GLM-5.3) | Router |")
    L.append("|---|---|---|---|")
    rowsdef = [("Total cost, 40 requests (₹)", "cost", "{:.4f}"), ("Cost per request (₹)", "cost_per_req", "{:.5f}"),
               ("p50 latency (ms)", "p50", "{:.0f}"), ("p95 latency (ms)", "p95", "{:.0f}"),
               ("p95 latency, live voice only (ms)", "q_voice_p95", "{:.0f}"),
               ("Mean quality (1-5)", "q", "{:.2f}"),
               ("Mean quality excl. fault-injected prompts", "q_clean", "{:.2f}"),
               ("Quality: hard slice", "q_hard", "{:.2f}"),
               ("Quality: hardest 10% (4 prompts)", "q_hardest", "{:.2f}"),
               ("Quality: English", "q_en", "{:.2f}"), ("Quality: Hindi/Punjabi/Hinglish", "q_indic", "{:.2f}"),
               ("Fallback fired (% of requests)", "fallback", "{:.0%}"), ("Gave up (count)", "gave_up", "{}")]
    for label, k, f in rowsdef:
        L.append(f"| {label} | " + " | ".join(f.format(S[c][k]) for c in CONFIGS) + " |")
    sav = 1 - S["router"]["cost"] / S["always_frontier"]["cost"]
    (s_lo, s_hi), (q_lo, q_hi) = bootstrap(data["router"], data["always_frontier"])
    L.append(f"\nRouter vs always-frontier: **{sav:.0%} cheaper** (95% bootstrap CI {s_lo:.0%} to {s_hi:.0%}); "
             f"quality difference {S['router']['q'] - S['always_frontier']['q']:+.2f} (CI {q_lo:+.2f} to {q_hi:+.2f}).")
    L.append("Router overhead (classification) per request: "
             f"mean {mean([r['router_overhead_ms'] for r in data['router']]):.3f} ms, 0 tokens, ₹0.\n")

    L.append("## 2. Per segment\n")
    L.append("| Segment | Config | Cost (₹) | p95 (ms) | Quality |")
    L.append("|---|---|---|---|---|")
    for t in ("bfsi", "telecom", "agri_gov"):
        for c in CONFIGS:
            rs = [r for r in data[c] if r["tenant"] == t]
            s = summarise(rs)
            L.append(f"| {t} | {c} | {s['cost']:.4f} | {s['p95']:.0f} | {s['q']:.2f} |")
    L.append("")

    L.append("## 3. Where the router sent traffic\n")
    L.append("| Rule | Requests | Final model(s) |")
    L.append("|---|---|---|")
    by_rule = {}
    for r in data["router"]:
        by_rule.setdefault(r["rule_id"], []).append(r["model"] or "none (template)")
    for k in sorted(by_rule):
        ms = {m: by_rule[k].count(m) for m in by_rule[k]}
        L.append(f"| {k} | {len(by_rule[k])} | " + ", ".join(f"{m} ×{n}" for m, n in ms.items()) + " |")
    misses = [r for r in data["router"] if r["difficulty"] == "hard" and not r["rule_id"].startswith(("R3", "R2-voice-hard"))]
    over = [r for r in data["router"] if r["difficulty"] != "hard" and r["rule_id"].startswith("R3")]
    L.append(f"\nHard prompts routed as not-hard (under-routing): {[r['id'] for r in misses]}. "
             f"Non-hard prompts routed as hard (over-routing): {[r['id'] for r in over]}.")
    hr = [r for r in data["router"] if r.get("human_review")]
    L.append(f"Human review flagged: {len(hr)} requests ({', '.join(r['id'] + ':' + r['human_review'] for r in hr)}).\n")

    # ---- Part 2 economics ----
    F = data["always_frontier"]
    head = {c: monthly(data[c], F, cfg) for c in CONFIGS}
    adj = {c: monthly(data[c], F, cfg, scale_out=True) for c in CONFIGS}
    hard2 = {c: monthly(data[c], F, cfg, weight=lambda r: 2.0 if r["difficulty"] == "hard" else 1.0)
             for c in CONFIGS}
    post = {m: (v["in_inr_per_m"], v["out_inr_per_m"]) for m, v in cfg["models"].items()}
    pi = cfg["post_intro_sarvam_price"]
    for m in ("sarvam-105b", "sarvam-105b-conversations"):
        post[m] = (pi["in_inr_per_m"], pi["out_inr_per_m"])
    postp = {c: monthly(data[c], F, cfg, prices=post) for c in CONFIGS}

    L.append("## 4. Part 2 economics: 50M input + 10M output tokens / month\n")
    L.append("| Configuration | Monthly cost (₹) | (US$) | Saving vs frontier |")
    L.append("|---|---|---|---|")
    for c in CONFIGS:
        L.append(f"| {c} | ₹{head[c]:,.0f} | ${head[c]/fx:,.0f} | {1-head[c]/head['always_frontier']:.0%} |")
    L.append(f"\n**Four numbers:** cheapest ₹{head['always_cheapest']:,.0f}, frontier ₹{head['always_frontier']:,.0f}, "
             f"router ₹{head['router']:,.0f}; router saves **{1-head['router']/head['always_frontier']:.0%}** vs frontier.\n")
    L.append("| Sensitivity | Cheapest | Frontier | Router | Router saving |")
    L.append("|---|---|---|---|---|")
    for label, d in (("Headline (fixed 10M output)", head),
                     ("Output scales with measured reasoning tokens", adj),
                     ("Hard traffic doubled", hard2),
                     ("Sarvam-105B intro price ends (assumed ₹13.5/₹45)", postp)):
        L.append(f"| {label} | ₹{d['always_cheapest']:,.0f} | ₹{d['always_frontier']:,.0f} | ₹{d['router']:,.0f} | "
                 f"{1-d['router']/d['always_frontier']:.0%} |")
    tin, tout = token_shares(data["router"])
    L.append("\nRouter token mix (share of input / output tokens): " + ", ".join(
        f"{m} {tin[m]/sum(tin.values()):.0%} / {tout.get(m,0)/sum(tout.values()):.0%}" for m in sorted(tin)))
    L.append(f"\nPrices: Sarvam list prices (₹/1M, ex-GST) as of {cfg['price_date']}; US$ at ₹{fx}/$.")

    (RES / "report.md").write_text("\n".join(L), encoding="utf8")
    (RES / "cost_quality.svg").write_text(svg_chart([(c, S[c]["cost"], S[c]["q"]) for c in CONFIGS]), encoding="utf8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
