"""
Build the README charts as static SVG files in docs/assets/.

    python scripts/make_charts.py

- All numbers come from the saved live results (results/tuning_v2/*,
  results/model_compare/*), so the charts always match the tables.
- Plain SVG, no plotting library: it shows up on GitHub in both light and
  dark mode (each file has its own colours and a prefers-color-scheme block)
  and diffs cleanly in git.
- Each setup keeps the same colour in every chart: Router = blue,
  Always-frontier (GLM-5.3) = orange, Always-cheapest = green. The green is
  a bit light on white, so every bar also has its value written next to it.
- Bars are flat at the baseline and rounded at the end; one scale per chart.
"""
import json
import math
import pathlib
import statistics
import sys
from collections import Counter, defaultdict

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from report import monthly  # noqa: E402

OUT = ROOT / "docs/assets"
RES = ROOT / "results/tuning_v2"
CONFIGS = ["router", "always_frontier", "always_cheapest"]
LABEL = {"router": "Router", "always_frontier": "Always-frontier (GLM-5.3)",
         "always_cheapest": "Always-cheapest (conversations)"}
SLOT = {"router": 1, "always_frontier": 2, "always_cheapest": 3}

STYLE = """<style>
  .viz { --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#8a8984; --grid:#e6e5e1;
         --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; }
  @media (prefers-color-scheme: dark) {
    .viz { --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#8f8e86; --grid:#33332f;
           --s1:#3987e5; --s2:#d95926; --s3:#199e70; } }
  text { font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; fill: var(--ink); }
  .t { font-size:15px; font-weight:600; } .st { font-size:12px; fill: var(--ink2); }
  .ax { font-size:11px; fill: var(--ink2); } .lab { font-size:11px; fill: var(--ink); }
  .note { font-size:10.5px; fill: var(--muted); }
  .grid { stroke: var(--grid); stroke-width:1; } .base { stroke: var(--muted); stroke-width:1; }
  .s1 { fill: var(--s1); } .s2 { fill: var(--s2); } .s3 { fill: var(--s3); } .sn { fill: var(--ink2); }
  .ring { stroke: var(--surface); stroke-width:2; }
</style>"""


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg(w, h, title, desc, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-labelledby="t d" class="viz">\n<title id="t">{esc(title)}</title>'
            f'<desc id="d">{esc(desc)}</desc>\n{STYLE}\n'
            f'<rect width="{w}" height="{h}" rx="8" style="fill:var(--surface)"/>\n{body}\n</svg>\n')


def hbar(x0, y, length, h, cls, r=4):
    """Horizontal bar: flat on the baseline (left), rounded data-end (right)."""
    if length <= 0:
        return ""
    r = min(r, length, h / 2)
    x1 = x0 + length
    return (f'<path class="{cls}" d="M{x0:.1f},{y:.1f} H{x1 - r:.1f} Q{x1:.1f},{y:.1f} {x1:.1f},{y + r:.1f} '
            f'V{y + h - r:.1f} Q{x1:.1f},{y + h:.1f} {x1 - r:.1f},{y + h:.1f} H{x0:.1f} Z"/>')


def vbar(x, y_base, height, w, cls, r=4):
    """Vertical bar: flat on the baseline (bottom), rounded data-end (top)."""
    if height <= 0:
        return ""
    r = min(r, height, w / 2)
    yt = y_base - height
    return (f'<path class="{cls}" d="M{x:.1f},{y_base:.1f} V{yt + r:.1f} Q{x:.1f},{yt:.1f} {x + r:.1f},{yt:.1f} '
            f'H{x + w - r:.1f} Q{x + w:.1f},{yt:.1f} {x + w:.1f},{yt + r:.1f} V{y_base:.1f} Z"/>')


def legend(x, y, items):
    out, cx = [], x
    for name, cls in items:
        out.append(f'<rect x="{cx}" y="{y - 9}" width="10" height="10" rx="2" class="{cls}"/>'
                   f'<text x="{cx + 15}" y="{y}" class="ax">{esc(name)}</text>')
        cx += 22 + 6.3 * len(name)
    return "".join(out)


def pct(xs, p):
    s = sorted(xs)
    return s[max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))]


def load():
    src = {json.loads(l)["id"]: json.loads(l) for l in open(ROOT / "data/tuning_v2.jsonl", encoding="utf8")}
    runs = {c: [json.loads(l) for l in open(RES / f"{c}.jsonl", encoding="utf8")] for c in CONFIGS}
    sc = {(json.loads(l)["id"], json.loads(l)["config"]): json.loads(l) for l in open(RES / "scores.jsonl", encoding="utf8")}
    return src, runs, sc


# ---------------------------------------------------------------- charts
def chart_cost_quality(src, runs, sc):
    """Scatter: cost for 75 requests (log scale) vs prompts passed."""
    pts = []
    for c in CONFIGS:
        pts.append((c, sum(r["cost_inr"] for r in runs[c]), sum(sc[(i, c)]["passed"] for i in src)))
    W, H, L, R, T, B = 720, 390, 70, 40, 70, 66
    xmin, xmax = math.log10(0.1), math.log10(100)
    ymin, ymax = 50, 75
    X = lambda v: L + (math.log10(v) - xmin) / (xmax - xmin) * (W - L - R)
    Y = lambda v: H - B - (v - ymin) / (ymax - ymin) * (H - T - B)
    b = [f'<text x="24" y="30" class="t">Router: more prompts passed, for about a tenth of the frontier cost</text>',
         f'<text x="24" y="50" class="st">75 live prompts. Up and to the left is better. Cost axis is logarithmic.</text>']
    for v in (0.1, 1, 10, 100):
        b.append(f'<line x1="{X(v):.1f}" y1="{T}" x2="{X(v):.1f}" y2="{H - B}" class="grid"/>'
                 f'<text x="{X(v):.1f}" y="{H - B + 16}" text-anchor="middle" class="ax">₹{v:g}</text>')
    for v in range(50, 76, 5):
        b.append(f'<line x1="{L}" y1="{Y(v):.1f}" x2="{W - R}" y2="{Y(v):.1f}" class="grid"/>'
                 f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" text-anchor="end" class="ax">{v}</text>')
    b.append(f'<text x="{(L + W - R) / 2}" y="{H - 18}" text-anchor="middle" class="ax">Cost for 75 requests (₹, log scale)</text>'
             f'<text x="18" y="{(T + H - B) / 2}" transform="rotate(-90 18 {(T + H - B) / 2})" text-anchor="middle" class="ax">Prompts passed (of 75)</text>')
    for c, cost, p in pts:
        x, y = X(cost), Y(p)
        anchor, dx = ("end", -14) if c == "always_frontier" else ("start", 14)
        b.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" class="s{SLOT[c]} ring"/>'
                 f'<text x="{x + dx:.1f}" y="{y - 4:.1f}" text-anchor="{anchor}" class="lab" font-weight="600">{esc(LABEL[c])}</text>'
                 f'<text x="{x + dx:.1f}" y="{y + 11:.1f}" text-anchor="{anchor}" class="ax">{p} passed · ₹{cost:.2f}</text>')
    b.append(f'<text x="24" y="{H - 4}" class="note">Router: 68 in the full run; 70 counting the two fixes verified afterwards (u49, u61).</text>')
    return svg(W, H, "Cost vs prompts passed", "Scatter of three configurations: " +
               "; ".join(f"{LABEL[c]} {p} passed at ₹{cost:.2f}" for c, cost, p in pts), "\n".join(b))


def chart_task_passes(src, runs, sc):
    """Grouped horizontal bars: pass rate by task type, three configurations."""
    cats = [("classification", "Labels"), ("extraction", "JSON extraction"), ("drafting", "Drafted replies"),
            ("summary", "Summaries"), ("translation", "Translation"), ("reasoning", "Calculations"),
            ("qa", "Long-doc Q&A, guards"), ("support_reply", "Live voice"), ("compliance", "Compliance")]
    W, L, R, T = 720, 170, 60, 86
    gh, bh, gap = 46, 11, 2
    H = T + gh * len(cats) + 40
    X = lambda v: L + v * (W - L - R)
    b = [f'<text x="24" y="30" class="t">Pass rate by task type</text>',
         f'<text x="24" y="50" class="st">75 live prompts, scored against the author\'s rubrics. Share of prompts at or above the pass mark.</text>',
         legend(24, 72, [(LABEL[c], f"s{SLOT[c]}") for c in CONFIGS])]
    for v in (0, 0.25, 0.5, 0.75, 1):
        b.append(f'<line x1="{X(v):.1f}" y1="{T - 4}" x2="{X(v):.1f}" y2="{H - 34}" class="grid"/>'
                 f'<text x="{X(v):.1f}" y="{H - 20}" text-anchor="middle" class="ax">{v:.0%}</text>')
    for gi, (cat, name) in enumerate(cats):
        ids = [i for i in src if src[i]["category"] == cat]
        y0 = T + gi * gh
        b.append(f'<text x="{L - 10}" y="{y0 + 21}" text-anchor="end" class="lab">{esc(name)}</text>'
                 f'<text x="{L - 10}" y="{y0 + 34}" text-anchor="end" class="note">n = {len(ids)}</text>')
        for k, c in enumerate(CONFIGS):
            rate = sum(sc[(i, c)]["passed"] for i in ids) / len(ids)
            y = y0 + 4 + k * (bh + gap)
            b.append(hbar(L, y, X(rate) - L, bh, f"s{SLOT[c]}"))
            b.append(f'<text x="{X(rate) + 5:.1f}" y="{y + 9.5:.1f}" class="note">{rate:.0%}</text>')
    b.append(f'<line x1="{L}" y1="{T - 4}" x2="{L}" y2="{H - 34}" class="base"/>')
    return svg(W, H, "Pass rate by task type", "Grouped bars: pass rate for each task type for the router and both baselines.", "\n".join(b))


def chart_latency(src, runs, sc):
    """Grouped vertical bars: p50, p95, and live-voice p95 latency (seconds)."""
    metrics = [("p50", "Typical (p50)"), ("p95", "Slowest 5% (p95)"), ("voice", "Live voice, p95")]
    vals = {}
    for c in CONFIGS:
        lat = [r["latency_ms"] / 1000 for r in runs[c] if r["latency_ms"] > 0]
        voice = [r["latency_ms"] / 1000 for r in runs[c] if src[r["id"]]["channel"] == "voice_live"]
        vals[c] = {"p50": pct(lat, 50), "p95": pct(lat, 95), "voice": pct(voice, 95)}
    W, H, L, R, T, B = 720, 360, 60, 30, 86, 60
    ymax = 30
    Y = lambda v: H - B - v / ymax * (H - T - B)
    gw = (W - L - R) / len(metrics)
    bw = 34
    b = [f'<text x="24" y="30" class="t">Latency: the router is as fast as the cheapest model on live calls</text>',
         f'<text x="24" y="50" class="st">Seconds, model time only (speech-to-text not included). Dashed line: 1.5 s voice target.</text>',
         legend(24, 72, [(LABEL[c], f"s{SLOT[c]}") for c in CONFIGS])]
    for v in range(0, ymax + 1, 5):
        b.append(f'<line x1="{L}" y1="{Y(v):.1f}" x2="{W - R}" y2="{Y(v):.1f}" class="grid"/>'
                 f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" text-anchor="end" class="ax">{v} s</text>')
    b.append(f'<line x1="{L}" y1="{Y(1.5):.1f}" x2="{W - R}" y2="{Y(1.5):.1f}" style="stroke:var(--ink2)" stroke-dasharray="4 3"/>')
    for mi, (m, name) in enumerate(metrics):
        gx = L + mi * gw + (gw - 3 * bw - 2 * 6) / 2
        for k, c in enumerate(CONFIGS):
            v = vals[c][m]
            x = gx + k * (bw + 6)
            b.append(vbar(x, H - B, H - B - Y(v), bw, f"s{SLOT[c]}"))
            ly = min(Y(v) - 5, Y(1.5) - 6)   # never sit on the dashed target line
            b.append(f'<text x="{x + bw / 2:.1f}" y="{ly:.1f}" text-anchor="middle" class="note">{v:.1f}</text>')
        b.append(f'<text x="{L + mi * gw + gw / 2:.1f}" y="{H - B + 18}" text-anchor="middle" class="lab">{esc(name)}</text>')
    b.append(f'<line x1="{L}" y1="{H - B}" x2="{W - R}" y2="{H - B}" class="base"/>')
    return svg(W, H, "Latency by configuration", "Grouped bars of p50, p95 and live-voice p95 latency in seconds.", "\n".join(b)), vals


def chart_monthly(src, runs, sc, cfg):
    """Horizontal bars: Part 2 monthly cost for 50M input + 10M output tokens."""
    fr = runs["always_frontier"]
    head = {c: monthly(runs[c], fr, cfg) for c in CONFIGS}
    W, L, R, T = 720, 220, 90, 70
    bh, gap = 26, 16
    H = T + 3 * (bh + gap) + 50
    vmax = 12000
    X = lambda v: L + v / vmax * (W - L - R)
    b = [f'<text x="24" y="30" class="t">Part 2: monthly cost for 50M input + 10M output tokens</text>',
         f'<text x="24" y="50" class="st">Each configuration\'s live token mix, priced at Sarvam list prices (₹, ex-GST).</text>']
    for v in range(0, vmax + 1, 3000):
        b.append(f'<line x1="{X(v):.1f}" y1="{T - 6}" x2="{X(v):.1f}" y2="{H - 40}" class="grid"/>'
                 f'<text x="{X(v):.1f}" y="{H - 26}" text-anchor="middle" class="ax">₹{v:,}</text>')
    order = ["always_frontier", "router", "always_cheapest"]
    for k, c in enumerate(order):
        y = T + k * (bh + gap)
        save = 1 - head[c] / head["always_frontier"]
        tag = "" if c == "always_frontier" else f"  (−{save:.0%})"
        b.append(f'<text x="{L - 10}" y="{y + bh / 2 + 4}" text-anchor="end" class="lab">{esc(LABEL[c])}</text>')
        b.append(hbar(L, y, X(head[c]) - L, bh, f"s{SLOT[c]}"))
        b.append(f'<text x="{X(head[c]) + 6:.1f}" y="{y + bh / 2 + 4}" class="lab" font-weight="600">₹{head[c]:,.0f}{tag}</text>')
    b.append(f'<line x1="{L}" y1="{T - 6}" x2="{L}" y2="{H - 40}" class="base"/>')
    return svg(W, H, "Monthly cost by configuration", "; ".join(f"{LABEL[c]} ₹{head[c]:,.0f}" for c in order), "\n".join(b)), head


def chart_spend_mix(runs):
    """Paired bars per model: share of router requests vs share of router spend."""
    rows = runs["router"]
    req = Counter(r["model"] or "template" for r in rows)
    spend = defaultdict(float)
    for r in rows:
        for a in r["attempts"]:
            spend[a["model"]] += a["cost_inr"]
    total_req, total_spend = len(rows), sum(spend.values())
    models = [("sarvam-105b-conversations", "conversations"), ("sarvam-105b", "sarvam-105b"),
              ("glm-5.3", "glm-5.3"), ("glm-5.3-flash", "glm-5.3-flash"), ("template", "rule reply, no model")]
    W, L, R, T = 720, 170, 60, 86
    gh, bh, gap = 44, 13, 2
    H = T + gh * len(models) + 40
    X = lambda v: L + v * (W - L - R)
    b = [f'<text x="24" y="30" class="t">Where the router sends traffic, and where the money goes</text>',
         f'<text x="24" y="50" class="st">75 live prompts. GLM-5.3 answers few requests but takes most of the spend.</text>',
         legend(24, 72, [("Share of router requests", "sn"), ("Share of router spend", "s1")])]
    for v in (0, 0.25, 0.5, 0.75, 1):
        b.append(f'<line x1="{X(v):.1f}" y1="{T - 4}" x2="{X(v):.1f}" y2="{H - 34}" class="grid"/>'
                 f'<text x="{X(v):.1f}" y="{H - 20}" text-anchor="middle" class="ax">{v:.0%}</text>')
    for gi, (m, name) in enumerate(models):
        y0 = T + gi * gh
        rq, sp = req.get(m, 0) / total_req, spend.get(m, 0) / total_spend
        b.append(f'<text x="{L - 10}" y="{y0 + 18}" text-anchor="end" class="lab">{esc(name)}</text>')
        for k, (v, cls) in enumerate(((rq, "sn"), (sp, "s1"))):
            y = y0 + 3 + k * (bh + gap)
            b.append(hbar(L, y, X(v) - L, bh, cls))
            b.append(f'<text x="{X(v) + 5:.1f}" y="{y + 10.5:.1f}" class="note">{v:.0%}</text>')
    b.append(f'<line x1="{L}" y1="{T - 4}" x2="{L}" y2="{H - 34}" class="base"/>')
    data = {m: (req.get(m, 0), req.get(m, 0) / total_req, spend.get(m, 0), spend.get(m, 0) / total_spend) for m, _ in models}
    return svg(W, H, "Router traffic and spend by model", "Share of requests and share of spend per model.", "\n".join(b)), data


def chart_models():
    """Small multiples (one axis each): passes and cost per model, 36-prompt comparison."""
    rows = [json.loads(l) for l in open(ROOT / "results/model_compare/rubric_scores_all.jsonl", encoding="utf8")]
    models = [("glm-5.3", "GLM-5.3"), ("sarvam-105b", "Sarvam-105B"), ("glm-5.3-flash", "GLM-5.3 Flash"),
              ("sarvam-105b-conversations", "105b-conversations")]
    d = {m: (sum(x["passed"] for x in rows if x["model"] == m), sum(x["cost_inr"] for x in rows if x["model"] == m))
         for m, _ in models}
    W, L, T, bh, gap = 720, 150, 76, 24, 12
    H = T + 4 * (bh + gap) + 40
    pw = 220
    X1 = lambda v: L + v / 36 * pw
    L2 = L + pw + 140
    X2 = lambda v: L2 + v / 10 * (W - L2 - 70)
    b = [f'<text x="24" y="30" class="t">Each model alone, same 36 prompts</text>',
         f'<text x="24" y="50" class="st">Left: prompts passed (of 36). Right: total cost for the 36 prompts (₹).</text>',
         f'<text x="{L}" y="{T - 8}" class="ax" font-weight="600">Passed (of 36)</text>',
         f'<text x="{L2}" y="{T - 8}" class="ax" font-weight="600">Cost for 36 prompts</text>']
    for k, (m, name) in enumerate(models):
        y = T + k * (bh + gap)
        p, c = d[m]
        b.append(f'<text x="{L - 10}" y="{y + bh / 2 + 4}" text-anchor="end" class="lab">{esc(name)}</text>')
        b.append(hbar(L, y, X1(p) - L, bh, "sn"))
        b.append(f'<text x="{X1(p) + 6:.1f}" y="{y + bh / 2 + 4}" class="lab">{p}</text>')
        b.append(hbar(L2, y, max(2, X2(c) - L2), bh, "sn"))
        b.append(f'<text x="{max(L2 + 2, X2(c)) + 6:.1f}" y="{y + bh / 2 + 4}" class="lab">₹{c:.2f}</text>')
    b.append(f'<line x1="{L}" y1="{T - 2}" x2="{L}" y2="{H - 36}" class="base"/>'
             f'<line x1="{L2}" y1="{T - 2}" x2="{L2}" y2="{H - 36}" class="base"/>')
    b.append(f'<text x="24" y="{H - 14}" class="note">Every model at default effort, 60 s timeout, live Sarvam API. Scored against the author\'s rubrics.</text>')
    return svg(W, H, "Single-model comparison", "; ".join(f"{n}: {d[m][0]} passed, ₹{d[m][1]:.2f}" for m, n in models), "\n".join(b)), d


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(open(ROOT / "config/models.yaml", encoding="utf8"))
    src, runs, sc = load()
    files = {"chart-cost-quality.svg": chart_cost_quality(src, runs, sc),
             "chart-task-passes.svg": chart_task_passes(src, runs, sc)}
    lat_svg, lat = chart_latency(src, runs, sc)
    mon_svg, mon = chart_monthly(src, runs, sc, cfg)
    mix_svg, mix = chart_spend_mix(runs)
    mod_svg, mod = chart_models()
    files.update({"chart-latency.svg": lat_svg, "chart-monthly-cost.svg": mon_svg,
                  "chart-spend-mix.svg": mix_svg, "chart-models.svg": mod_svg})
    for name, text in files.items():
        (OUT / name).write_text(text, encoding="utf8")
        print("wrote", OUT / name)
    print("latency", {c: {k: round(v, 2) for k, v in lat[c].items()} for c in lat})
    print("monthly", {c: round(v) for c, v in mon.items()})
    print("mix", {m: (n, f"{a:.0%}", round(s, 2), f"{b:.0%}") for m, (n, a, s, b) in mix.items()})
    print("models", mod)


if __name__ == "__main__":
    main()
