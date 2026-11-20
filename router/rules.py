"""
The routing rules: decide which model gets each request.

Rules are checked top to bottom and the first one that matches wins:

  R1  junk or attack     -> fixed reply or refusal, no model call (costs nothing)
                            ("attack" includes role-play like "you are now the bank
                             manager" and asking for other customers' data)
  R2  live voice         -> easy: sarvam-105b-conversations
                            hard: sarvam-105b at low effort + a "one moment" phrase
  R3c compliance check   -> glm-5.3 > flash > sarvam-105b, in any language
  R4  label instruction  -> "Classify ... return only the label" style prompts
                            (checked before R3, see the note in route())
  R3  hard               -> Indic or mixed language: sarvam-105b at high effort
                            English: glm-5.3, including calculations
  R4  simple             -> sarvam-105b-conversations > 105b > flash (labels, extraction)
  R4b language task      -> sarvam-105b-conversations > 105b > flash (translate, summarise, reply)
  R5  everything else    -> sarvam-105b-conversations > 105b
  R6  after the answer   -> does a person need to check it? (see review.py)

Why this order:
  - R1 first, so we never pay to answer gibberish or an injection attempt.
  - R2 before R3, because on a live call speed matters more than depth.
    Three seconds of silence is worse than a slightly weaker answer.
  - R3 before the simple rules: if a request looks both hard and simple,
    treat it as hard. When unsure, lean towards quality over cost.
  - Hard questions in Indian languages stay on Sarvam. Sarvam-105B is built
    for Indic languages, GLM's reasoning edge mostly disappears outside
    English, and Sarvam is about 13x cheaper on input.

Fallback ladders:
Each decision has a list of models: the first choice, then what to try if it
times out, errors, returns bad JSON or refuses a normal request.
  - Hard Indic tries Flash before full GLM-5.3: a failure there is usually
    about availability or format, not about the question being too hard.
  - When GLM-5.3 is first (hard English, compliance), it falls back to Flash
    and then 105B, so a GLM outage doesn't take the customer down.
  - R4 and R4b fall back to 105B, then Flash. R5 falls back to 105B.
Ladders have at most 3 steps (so at most 2 escalations).

Why R4/R4b use the conversations model (live comparison, 2026-11-18):
cheapest per token isn't cheapest per request. Sarvam-105B spends 400-500
hidden reasoning tokens even on a one-word label, even at low effort.
sarvam-105b-conversations doesn't reason in the background, and on labels,
extraction, translation, summaries and replies it passed 19 of 20 prompts at
about 1/15th of 105B's cost and ~0.3 s latency.

Every decision comes with a rule_id and a short reason, and both are logged,
so you can always see why a request went where it did.
"""
from dataclasses import dataclass, field

from .classify import Classification

JUNK_REPLY = {
    "en": "Sorry, I didn't catch that. Could you rephrase your question?",
    "indic": "माफ़ कीजिए, मैं समझ नहीं पाया। क्या आप अपना सवाल दोबारा लिख सकते हैं? / ਮਾਫ਼ ਕਰਨਾ, ਕਿਰਪਾ ਕਰਕੇ ਆਪਣਾ ਸਵਾਲ ਦੁਬਾਰਾ ਲਿਖੋ।",
}
# Refusal for injection / role-play / other people's data. The rubric asks for
# three things: say no, reveal nothing, and point to the proper way to do it.
REFUSAL_REPLY = {
    "en": "I can't do that: I can't act as bank staff, approve loans, or share internal or other "
          "customers' information. For your own account, please use the bank's official app or visit "
          "your branch, and I'm happy to explain the process or the documents you'll need.",
    "hinglish": "Main yeh nahi kar sakta: main bank staff ki tarah loan approve nahi kar sakta, na hi kisi ki "
                "niji ya internal jaankari de sakta hoon. Apne account ke liye bank ka official app use karein "
                "ya branch jaayein; main process ya zaroori documents samjha sakta hoon.",
    "hi": "मैं ऐसा नहीं कर सकता: मैं बैंक कर्मचारी की तरह लोन मंज़ूर नहीं कर सकता और न ही किसी की निजी या "
          "आंतरिक जानकारी दे सकता हूँ। अपने खाते के लिए बैंक का आधिकारिक ऐप इस्तेमाल करें या शाखा जाएँ; "
          "मैं प्रक्रिया या ज़रूरी दस्तावेज़ समझा सकता हूँ।",
    "pa": "ਮੈਂ ਇਹ ਨਹੀਂ ਕਰ ਸਕਦਾ: ਮੈਂ ਬੈਂਕ ਕਰਮਚਾਰੀ ਵਾਂਗ ਲੋਨ ਮਨਜ਼ੂਰ ਨਹੀਂ ਕਰ ਸਕਦਾ ਅਤੇ ਨਾ ਹੀ ਕਿਸੇ ਦੀ ਨਿੱਜੀ ਜਾਂ "
          "ਅੰਦਰੂਨੀ ਜਾਣਕਾਰੀ ਦੇ ਸਕਦਾ ਹਾਂ। ਆਪਣੇ ਖਾਤੇ ਲਈ ਬੈਂਕ ਦੀ ਅਧਿਕਾਰਤ ਐਪ ਵਰਤੋ ਜਾਂ ਬ੍ਰਾਂਚ ਜਾਓ; ਮੈਂ ਪ੍ਰਕਿਰਿਆ "
          "ਜਾਂ ਲੋੜੀਂਦੇ ਦਸਤਾਵੇਜ਼ ਸਮਝਾ ਸਕਦਾ ਹਾਂ।",
}


def _reply_lang(c) -> str:
    """Reply in the script the customer wrote in: Gurmukhi -> Punjabi,
    Devanagari -> Hindi, romanised -> Hinglish, otherwise English."""
    if "gurmukhi" in c.scripts:
        return "pa"
    if "devanagari" in c.scripts:
        return "hi"
    return "hinglish" if c.language == "code_switched" else "en"


# System instruction for labelling / extraction tasks (R4). Added after the
# live run, where the conversations model called a plain statement ("Mera loan
# statement mil gaya") positive, wrote an amount as a string ("6000"), and once
# gave a label in Hindi. Temperature 0 keeps the answers repeatable.
LABEL_INSTRUCTION = (
    "You label and extract data for a bank's systems. Reply with ONLY the label or the JSON asked "
    "for, with no other words. Labels: use exactly one of the labels given, in lowercase English. "
    "For sentiment: 'positive' only if the customer praises or thanks, 'negative' only if they "
    "complain or are unhappy (including sarcasm), otherwise 'neutral', e.g. a plain statement of "
    "fact such as 'I received my statement'. JSON: keep every value in the exact format asked for "
    "(e.g. a date written as '5 Nov', with a capital letter); write numbers as plain numbers "
    "without commas or quotes."
)
# Said to a live caller while the slower model works on a hard question.
HOLDING_PHRASE = {"en": "One moment, let me check that for you.", "indic": "एक मिनट, मैं देख कर बताता हूँ।"}


@dataclass
class Step:
    model: str
    effort: str = "default"      # low | default | high (reasoning budget)


@dataclass
class Decision:
    rule_id: str
    reason: str
    ladder: list = field(default_factory=list)   # [Step, ...]; empty = no model call
    template: str | None = None                  # canned reply when no model call
    holding_phrase: str | None = None
    instruction: str | None = None               # system instruction sent with the request
    temperature: float | None = None             # None = model default


def _allowed(ladder, tenant):
    """Remove models this tenant isn't allowed to use (e.g. a site that can't
    host one). If nothing is left, use sarvam-105b."""
    ok = [s for s in ladder if s.model in tenant["allowed_models"]]
    return ok or [Step("sarvam-105b")]


def route(req: dict, c: Classification, tenant: dict) -> Decision:
    lang_key = "en" if c.language == "en" else "indic"
    live = req.get("channel") == "voice_live"
    task_tag = req.get("task_tag", "")

    # A tenant can list task types that must always take the hard path
    # ("never_route_down" in its config), whatever the wording.
    protected = task_tag in tenant.get("never_route_down", [])
    is_hard = bool(c.hard_cues) or protected
    why_hard = c.hard_cues[:2] or [f"protected task '{task_tag}'"]

    # R1: junk or attack -> canned reply, no model call.
    # Attack is checked first so an injection attempt never gets the friendlier
    # "please rephrase" reply.
    if c.is_attack:
        return Decision("R1-attack", "matched prompt-injection cue; canned refusal, no model call",
                        template=REFUSAL_REPLY[_reply_lang(c)])
    if c.is_junk:
        return Decision("R1-junk", "too short / gibberish; templated rephrase request, no model call",
                        template=JUNK_REPLY[lang_key])

    # R2: live voice call -> speed first. Easy questions go to the fast
    # conversations model; hard ones go to 105B at low effort, with a holding
    # phrase so the caller isn't left in silence.
    if live and not is_hard:
        return Decision("R2-voice-easy", "live call, no hard cue: low-latency conversational model",
                        _allowed([Step("sarvam-105b-conversations"), Step("sarvam-105b", "low"),
                                  Step("glm-5.3-flash", "low")], tenant))
    if live:
        return Decision("R2-voice-hard", f"live call with hard cue {why_hard}: 105B low effort + holding phrase",
                        _allowed([Step("sarvam-105b", "low"), Step("glm-5.3-flash", "low")], tenant),
                        holding_phrase=HOLDING_PHRASE[lang_key])

    # R3c: compliance check -> strongest model first, in any language.
    # This sits above the other hard rules and above R4 so that a prompt
    # asking for a "yes or no" answer can't push a compliance question
    # down to a cheap model.
    if c.compliance_cues or task_tag == "compliance":
        why = c.compliance_cues[:2] or ["task tag 'compliance'"]
        return Decision("R3c-compliance", f"compliance cue {why}: strongest model first",
                        _allowed([Step("glm-5.3"), Step("glm-5.3-flash"), Step("sarvam-105b")], tenant))

    # R4 (checked early): a clear label / extract instruction ("Classify ...
    # Return only the label", "Extract ... as JSON") beats hard-sounding words
    # inside the message being labelled. Found on u04: "interest rate" in the
    # customer's message was sending a one-word label job to 105B at high effort.
    if c.label_instruction:
        return Decision("R4-simple", f"explicit label/extract instruction {c.simple_cues[:2]}: conversations model "
                        "(hard words inside the message are ignored)",
                        _allowed([Step("sarvam-105b-conversations"), Step("sarvam-105b"),
                                  Step("glm-5.3-flash")], tenant),
                        instruction=LABEL_INSTRUCTION, temperature=0.0)

    # R3: hard question -> the language decides: Indic or mixed stays on
    # Sarvam-105B (high effort), English goes to GLM-5.3.
    if is_hard and c.language != "en":
        return Decision("R3-hard-indic", f"hard cue {why_hard} in {c.language}: Sarvam-105B high effort",
                        _allowed([Step("sarvam-105b", "high"), Step("glm-5.3-flash", "high"),
                                  Step("glm-5.3")], tenant))
    if is_hard:
        return Decision("R3-hard-en", f"hard cue {why_hard} in English: frontier model",
                        _allowed([Step("glm-5.3"), Step("glm-5.3-flash"),
                                  Step("sarvam-105b")], tenant))

    # R4: simple task (labels, extraction) -> conversations model. It doesn't
    # spend hidden reasoning tokens; it scored 10.5 of 11 in testing at about
    # 1/15th of 105B's cost and ~0.2 s.
    if c.simple_cues:
        return Decision("R4-simple", f"simple-task cue {c.simple_cues[:2]}: conversations model (no reasoning tokens)",
                        _allowed([Step("sarvam-105b-conversations"), Step("sarvam-105b"),
                                  Step("glm-5.3-flash")], tenant),
                        instruction=LABEL_INSTRUCTION, temperature=0.0)

    # R4b: language task (translate, summarise, write a reply) -> conversations
    # model. It passed all 9 of these in the live comparison and was the
    # cheapest and fastest.
    if c.language_task_cues:
        return Decision("R4b-language-task", f"language-task cue {c.language_task_cues[:2]}: conversations model",
                        _allowed([Step("sarvam-105b-conversations"), Step("sarvam-105b"),
                                  Step("glm-5.3-flash")], tenant))

    # R5: anything else -> conversations model, then 105B. In the live
    # comparison the two scored the same overall (29/36 each), but the
    # conversations model cost about 1/7th as much and was ~10x faster.
    return Decision("R5-default", "no hard, simple or language-task cue: conversations model",
                    _allowed([Step("sarvam-105b-conversations"), Step("sarvam-105b")], tenant))


# R6 (human review) lives in router/review.py since it looks at the answer,
# not the request. Imported here so `from router.rules import needs_human`
# keeps working.
from .review import needs_human  # noqa: E402,F401
