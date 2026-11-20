"""
Quality scoring: gives every answer a score from 1 to 5.

The score comes from a model judge, but simple hard checks can cap it.

1. Hard checks (run in every mode):
     - JSON tasks: is the output valid JSON?
     - Language: did a Hindi/Punjabi question get its answer in the same script?
       A right answer in the wrong language is still useless to a farmer on
       an IVR line.
   Failing either check caps the score at 2, whatever the judge says.
2. Model judge (real mode): GLM-5.3 at high effort grades the answer against
   the prompt's rubric and reference answer. GLM-5.3 is also one of the
   models being compared, so it may like its own style. The rubric, the
   reference answer and a hand check of some Hindi/Punjabi answers help
   keep that in check. The judge's cost is not counted in routing cost.
3. Mock mode: uses the simulated quality from call.py (judge="mock").

Things this score can't capture: tone and politeness in Hindi/Punjabi,
cultural nuance, factual mistakes the judge also misses, how slow a live
call feels, whether advice is correct under regulation, and real traffic
beyond the test prompts.
"""
import json
import re

from .classify import INDIC_RANGES

JUDGE_PROMPT = """You are grading a support bot's answer for an Indian enterprise customer.
Question:
{prompt}

Reference answer / rubric:
{rubric}

Bot's answer:
{answer}

Score 1-5: 5 = correct, complete, right language and tone; 4 = minor issues;
3 = partly correct or missing something important; 2 = mostly wrong; 1 = wrong or harmful.
Reply with JSON only: {{"score": <1-5>, "why": "<one sentence>"}}"""


def _script_of(text: str) -> str | None:
    for name, (lo, hi) in INDIC_RANGES.items():
        if any(lo <= ord(ch) <= hi for ch in text):
            return name
    return None


def deterministic_checks(req: dict, answer: str) -> list[str]:
    """Return the names of any hard checks the answer fails (empty list = all good)."""
    fails = []
    if req.get("expects_json"):
        try:
            json.loads(answer.strip().removeprefix("```json").removesuffix("```").strip())
        except ValueError:
            fails.append("invalid_json")
    want = req.get("expected_script")          # e.g. "devanagari", "gurmukhi"
    if want and _script_of(answer) != want:
        fails.append(f"wrong_script(expected {want})")
    return fails


def score(req: dict, result: dict, mock: bool, cfg: dict) -> dict:
    final = result["final"]
    if result.get("template") is not None:
        # R1 fixed replies: if the prompt really was junk/attack, the canned
        # reply is exactly right (5); if not, a real question got blocked (1).
        return {"quality": 5.0 if req["category"] in ("junk", "attack") else 1.0,
                "judge": "rule", "checks_failed": []}
    if final is None:
        return {"quality": 1.0, "judge": "gave_up", "checks_failed": ["no_answer"]}
    if mock:
        return {"quality": final["mock_quality"], "judge": "mock", "checks_failed": []}
    if cfg.get("_judge") == "human":
        # Left blank here and scored later by hand against the rubric.
        return {"quality": None, "judge": "pending_human", "checks_failed": deterministic_checks(req, final["text"])}

    from .call import real_call
    fails = deterministic_checks(req, final["text"])
    jp = JUDGE_PROMPT.format(prompt=req["prompt"], rubric=req.get("rubric", ""), answer=final["text"])
    j = real_call({"id": req["id"] + "-judge", "category": "judge"}, jp, "glm-5.3", "high", 0, cfg)
    m = re.search(r'"score"\s*:\s*([1-5])', j.get("text", ""))
    q = float(m.group(1)) if m else 3.0        # unreadable judge reply -> neutral 3
    if fails:
        q = min(q, 2.0)
    return {"quality": q, "judge": "glm-5.3", "checks_failed": fails}
