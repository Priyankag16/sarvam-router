"""
Score the SIMPLE tasks (classification labels + JSON extraction) for every
model run, using the spreadsheet rubrics, and compare cost / latency / tokens.

    python scripts/score_simple.py

Simple tasks are the 11 prompts that ask for a label or a JSON extraction
(u01-u07, u11, u12, u24, u25). Their rubrics are objective, so the script
applies them exactly as the sheet says:
  Label: 1 = just the correct label (any case, quotes and a final full stop
         ignored), 0.5 = correct label plus extra text, 0 = wrong.
  JSON:  0 if it isn't valid JSON, has extra text, or has keys other than
         amount + date. Otherwise 0.5 for the amount (a number, not a string
         with commas) + 0.5 for the date.
u28-u30 are also marked "classification" in the sheet, but they are really
pass/fail behaviour checks (junk / guard prompts), so they're left out here.
"""
import json
import pathlib
import re
import statistics

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = {json.loads(l)["id"]: json.loads(l) for l in open(ROOT / "data/tuning.jsonl", encoding="utf8")}
SIMPLE = [i for i, s in SRC.items() if s["category"] in ("classification", "extraction")
          and i not in ("u28", "u29", "u30")]
RUNS = {
    "glm-5.3 (default)": "results/model_compare/fixed_glm-5.3.jsonl",
    "glm-5.3-flash (default)": "results/model_compare/fixed_glm-5.3-flash.jsonl",
    "sarvam-105b (default)": "results/model_compare/fixed_sarvam-105b.jsonl",
    "sarvam-105b-conversations": "results/model_compare/fixed_sarvam-105b-conversations.jsonl",
    "sarvam-105b LOW (router run)": "results/tuning_live/router.jsonl",
}


def score_label(answer, gold):
    a = (answer or "").strip().strip('"\'`').rstrip(".").strip()
    if a.lower() == gold.lower():
        return 1.0, ""
    if re.search(rf"\b{re.escape(gold)}\b", a, re.I):
        return 0.5, "correct label + extra text"
    return 0.0, f"wrong: {a[:40]!r}"


def score_json(answer, gold):
    a = (answer or "").strip()
    a = re.sub(r"^```(?:json)?\s*|\s*```$", "", a).strip()
    try:
        d = json.loads(a)
    except ValueError:
        return 0.0, "invalid JSON / extra text"
    if not isinstance(d, dict) or set(d) != {"amount", "date"}:
        return 0.0, f"wrong keys {list(d) if isinstance(d, dict) else type(d).__name__}"
    g = json.loads(gold)
    s = 0.0
    notes = []
    if isinstance(d["amount"], (int, float)) and d["amount"] == g["amount"]:
        s += 0.5
    else:
        notes.append(f"amount {d['amount']!r}")
    if str(d["date"]).strip() == g["date"]:
        s += 0.5
    else:
        notes.append(f"date {d['date']!r}")
    return s, "; ".join(notes)


def pct(xs, p):
    s = sorted(xs)
    return s[max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))]


def main():
    out = ["# Simple tasks: model comparison (11 prompts, live API)\n"]
    table = ["| Model | Score (of 11) | Exact-right | Cost ₹ (11 req) | Avg reasoning tokens | p50 latency | p95 latency | Timeouts/errors |",
             "|---|---|---|---|---|---|---|---|"]
    detail = {}
    for name, path in RUNS.items():
        p = ROOT / path
        if not p.exists():
            table.append(f"| {name} | (no run) | | | | | | |")
            continue
        rows = {json.loads(l)["id"]: json.loads(l) for l in open(p, encoding="utf8")}
        tot, exact, cost, rsn, lat, fails = 0.0, 0, 0.0, [], [], 0
        for i in SIMPLE:
            r, s = rows[i], SRC[i]
            fn = score_json if s["category"] == "extraction" else score_label
            sc, note = fn(r.get("answer"), s["reference"])
            tot += sc
            exact += sc == 1.0
            cost += r["cost_inr"]
            rsn.append(r.get("reasoning_tokens", 0))
            lat.append(r["latency_ms"])
            fails += sum(a["status"] != "ok" for a in r["attempts"])
            detail.setdefault(i, {})[name] = (sc, note, (r.get("answer") or "").strip().replace("\n", " ⏎ ")[:70])
        table.append(f"| {name} | **{tot:g}** | {exact}/11 | {cost:.4f} | {statistics.mean(rsn):.0f} | "
                     f"{pct(lat, 50)/1000:.1f} s | {pct(lat, 95)/1000:.1f} s | {fails} |")
    out += table
    out.append("\n## Per prompt (score, note, answer)\n")
    for i in SIMPLE:
        s = SRC[i]
        out.append(f"**{i}** ({s['category']}, {s['lang']}) expected `{s['reference']}`")
        for name, (sc, note, ans) in detail.get(i, {}).items():
            out.append(f"- {name}: **{sc:g}** {note} → `{ans}`")
        out.append("")
    text = "\n".join(out)
    (ROOT / "results/model_compare/simple_tasks.md").write_text(text, encoding="utf8")
    print(text)


if __name__ == "__main__":
    main()
