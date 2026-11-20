"""
R6 human review: should a person check this answer before it goes out?

This runs after the answer is written and looks at what the answer does:
  HR1 timeline commitment    a reply promises a date or a time period
  HR2 product recommendation the customer asks which product to pick
  HR3 complaint reply        a reply to a customer reporting a problem
  HR4 compliance finding     a compliance check finds a failure ("disclosure_read: no")
  HR5 sensitive topic        optional, per customer (e.g. eligibility)

The default rules are in config/review_defaults.yaml. Each customer's
config/tenants/<name>.yaml can turn rules off or swap their patterns under
`human_review:`. merged_rules() puts the two together.

The first version just looked for keywords in the prompt. On the 75-prompt
tuning set it caught 0 of the 10 cases that needed review and raised 9 false
flags: words like "complaint" or "loan" rarely appear in the request itself,
but show up all the time in label lists, translations and transcripts.

It's plain pattern matching, no model call: about 0.013 ms per answer
(0.36 ms at worst), compared with ~325 ms for a model call.

For now every flag goes to the review queue, including on live calls.
"""
import copy
import pathlib
import re
from functools import lru_cache

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Answers from these rules never need review: STT confirmations, canned
# refusals / rephrase requests, and plain labels.
NEVER_REVIEW = {"R0-stt-confirm", "R1-attack", "R1-junk", "R4-simple"}
TRANSCRIPT_WORDS = ("transcript", "ट्रांसक्रिप्ट", "ਟ੍ਰਾਂਸਕ੍ਰਿਪਟ")


@lru_cache(maxsize=1)
def _defaults() -> dict:
    return yaml.safe_load(open(ROOT / "config/review_defaults.yaml", encoding="utf8"))


def merged_rules(tenant: dict) -> dict:
    """Start from the default rules and apply the tenant's `human_review:` changes on top."""
    base = copy.deepcopy(_defaults())
    override = tenant.get("human_review") or {}
    if not isinstance(override, dict):          # old keyword-list format, just ignore it
        return base
    if "reply_task_patterns" in override:
        base["reply_task_patterns"] = override["reply_task_patterns"]
    for name, cfg in (override.get("rules") or {}).items():
        base["rules"].setdefault(name, {}).update(cfg or {})
    return base


def _any(patterns, text) -> str | None:
    """Return the first pattern that matches the text, or None."""
    for p in patterns or []:
        if re.search(p, text, re.I):
            return p
    return None


def question_part(prompt: str) -> str:
    """The part of the prompt that is the actual question or instruction.
    For a transcript, that's just the first and last line, so words spoken
    inside the transcript don't trigger a flag."""
    lines = [l for l in prompt.splitlines() if l.strip()]
    if not lines:
        return ""
    if len(lines) > 2 and any(w in lines[0].lower() for w in TRANSCRIPT_WORDS):
        return lines[0] + "\n" + lines[-1]
    return prompt


def needs_human(req: dict, prompt: str, answer: str | None, rule_id: str, tenant: dict) -> dict | None:
    """Return {'action', 'rule', 'reason'} if a human must own this answer, else None."""
    if not answer or rule_id in NEVER_REVIEW:
        return None
    cfg = merged_rules(tenant)
    q = question_part(prompt)
    is_reply = bool(_any(cfg.get("reply_task_patterns"), q))
    is_voice = req.get("channel") == "voice_live"

    # Check rules in the configured order (most serious first); any rule not
    # listed in check_order is checked after those.
    order = cfg.get("check_order") or []
    names = [n for n in order if n in cfg["rules"]] + [n for n in cfg["rules"] if n not in order]
    for name in names:
        rule = cfg["rules"][name]
        if not rule.get("enabled", False):
            continue
        # Some rules only apply to customer replies (or live calls), or only
        # to answers from one routing rule (e.g. HR4 -> R3c-compliance).
        scope = rule.get("applies_to")
        if scope == "reply" and not is_reply:
            continue
        if scope == "reply_or_voice" and not (is_reply or is_voice):
            continue
        if rule.get("applies_to_rule") and rule_id != rule["applies_to_rule"]:
            continue
        # A rule fires only if every pattern list it has finds a match.
        # A list the rule doesn't define counts as matched.
        hit_q = _any(rule.get("question_patterns"), q) if rule.get("question_patterns") else True
        hit_p = _any(rule.get("product_patterns"), q) if rule.get("product_patterns") else True
        hit_a = _any(rule.get("answer_patterns"), answer) if rule.get("answer_patterns") else True
        if rule.get("question_patterns") == [] and not rule.get("answer_patterns"):
            continue                              # switched on but no patterns given: skip
        if hit_q and hit_p and hit_a:
            matched = next((m for m in (hit_q, hit_p, hit_a) if isinstance(m, str)), "")
            return {"action": "review_queue", "rule": name,
                    "reason": f"{rule.get('description', name)} (matched '{matched}')"}
    return None
