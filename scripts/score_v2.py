"""
Score the 75-prompt tuning set (v2) for the router and both baselines, and
build the results tables used in README §3b.

    python scripts/score_v2.py

25 prompts have objective rubrics and are scored here in code, following the
spreadsheet exactly:
  Exact match            : just the label = 1, label + extra text = 0.5, else 0
  Exact match + route    : same, but a correct label from the frontier model
                           only gets 0.5 (the sheet counts that as over-routing)
  JSON field match       : 0 if invalid or extra keys; else 0.5 for the amount
                           (as a number) + 0.5 for the date
  Exact match (±1 rupee) : the last line must be the number, within ±1
                           (₹ signs, commas and ** are stripped first)
  Exact match (meaning)  : the planted fact has to appear in the answer
The other 50 were scored against the sheet rubric by reading them. Those
scores, each with a one-line reason, are in
results/tuning_v2/claude_manual_scores.json so any number can be checked.
Pass = score >= the sheet's pass mark.
"""
import json
import pathlib
import re
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from score_simple import score_json, score_label  # noqa: E402

DATA = ROOT / "data/tuning_v2.jsonl"
RES = ROOT / "results/tuning_v2"
CONFIGS = ["router", "always_cheapest", "always_frontier"]
LABEL = {"router": "Router", "always_cheapest": "Always-cheapest (conversations)",
         "always_frontier": "Always-frontier (GLM-5.3)"}

# The planted fact for the long-transcript questions (any one form counts).
NEEDLE = {
    "u51": ["simran"],
    "u52": ["15 दिसंबर", "15 december"],
    "u53": ["9814012345"],
    "u54": ["punjabi", "ਪੰਜਾਬੀ", "पंजाबी"],
    "u55": ["7 pm", "7pm", "7:00 pm", "7 p.m"],
}


def score_number(answer, gold):
    """Calculation answers: the last non-empty line must be the right number (±1)."""
    lines = [l for l in (answer or "").strip().splitlines() if l.strip()]
    if not lines:
        return 0.0, "empty"
    last = re.sub(r"[₹*,`\s]|rs\.?|inr", "", lines[-1].strip().lower())
    try:
        v = float(last)
    except ValueError:
        return 0.0, f"last line not a number: {lines[-1][:30]!r}"
    return (1.0, "") if abs(v - float(gold)) <= 1 else (0.0, f"{v:g} vs {gold}")


def score_needle(i, answer):
    """Long-transcript questions: did the answer find the planted fact?"""
    # u53 is a phone number, so spaces are removed before matching.
    # u55: an answer that says 5 pm and not 7 pm is wrong, even if it matched.
    a =(answer or "").lower().replace(" ", "") if i == "u53" else (answer or "").lower()
    ok = any(n.lower() in a for n in NEEDLE[i])
    if i == "u55" and "5 pm" in a and "7 pm" not in a:
        ok = False
    return (1.0, "") if ok else (0.0, "planted fact missing or wrong")


def auto_score(s, r, config):
    """Score by the sheet's scoring method. Returns None if it needs reading by hand."""
    m, ans = s["scoring_method"], r.get("answer")
    if m == "Exact match":
        return score_label(ans, s["reference"])
    if m == "Exact match + route check":
        sc, note = score_label(ans, s["reference"])
        if sc == 1.0 and r.get("model") == "glm-5.3":
            return 0.5, "correct label but sent to the frontier model (over-routing)"
        return sc, note
    if m == "JSON field match":
        return score_json(ans, s["reference"])
    if m == "Exact match (±1 rupee)":
        return score_number(ans, s["reference"])
    if m == "Exact match (meaning)":
        return score_needle(s["id"], ans)
    return None


def pct(xs, p):
    s = sorted(xs)
    return s[max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))] if s else 0


def main():
    src = {json.loads(l)["id"]: json.loads(l) for l in open(DATA, encoding="utf8")}
    runs = {c: {json.loads(l)["id"]: json.loads(l) for l in open(RES / f"{c}.jsonl", encoding="utf8")}
            for c in CONFIGS}
    manual_path = RES / "claude_manual_scores.json"
    manual = json.loads(manual_path.read_text(encoding="utf8")) if manual_path.exists() else {}
    rows, missing = [], []
    for i, s in src.items():
        for c in CONFIGS:
            r = runs[c][i]
            a = auto_score(s, r, c)
            if a is not None:
                sc, note, judge = a[0], a[1], "auto"
            elif i in manual and c in manual[i]:
                sc, note, judge = manual[i][c][0], manual[i][c][1], "rubric_review"
            else:
                missing.append((i, c))
                continue
            rows.append({"id": i, "config": c, "category": s["category"], "lang": s["lang"],
                         "difficulty": s["difficulty"], "score": sc, "max_score": s["max_score"],
                         "pass_mark": s["pass_mark"], "passed": sc >= s["pass_mark"], "note": note,
                         "judge": judge, "model": r.get("model"), "rule_id": r.get("rule_id"),
                         "cost_inr": r["cost_inr"], "latency_ms": r["latency_ms"],
                         "in_tokens": r["in_tokens"], "out_tokens": r["out_tokens"],
                         "reasoning_tokens": r.get("reasoning_tokens", 0),
                         "fallback": r["fallback_fired"], "gave_up": r["gave_up"],
                         "empty": not (r.get("answer") or "").strip(),
                         "hr_got": bool(r.get("human_review")), "hr_want": s["expected_human_review"]})
    if missing:
        print(f"{len(missing)} answers still need manual scores, e.g. {missing[:6]}")
    with open(RES / "scores.jsonl", "w", encoding="utf8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"scored {len(rows)} answers -> {RES / 'scores.jsonl'}")


if __name__ == "__main__":
    main()
