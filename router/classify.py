"""
Step 0: work out what kind of request this is.

Before picking a model the router needs a few quick facts:
  language     English, an Indic script, or a mix (e.g. Hinglish)
  size         rough input token count (Indic scripts use more tokens per word)
  junk/attack  gibberish, or someone trying to break the bot
  hard cues    words that suggest reasoning, maths or a compliance question
  simple cues  words that suggest a label / extract / classify job

This is done with keyword lists and Unicode ranges rather than a model, because:
  - it costs nothing per request,
  - it takes well under a millisecond,
  - every decision can be explained ("matched 'eligib'"), and
  - it works on an air-gapped server with no extra model.
The downside: a hard question with none of the cue words is treated as a
normal one. The eval checks how often that happens.

The time spent here (overhead_ms) is added to each request's latency so the
router isn't shown as faster than it really is.
"""
import re
import time
from dataclasses import dataclass, field

# Unicode blocks for the main Indic scripts. Any character in one of these
# ranges means the text is at least partly in an Indian language.
# The router handles all of them, but the test set only has Hindi, Punjabi and
# English (plus romanised / mixed forms), since those are the ones I can check.
INDIC_RANGES = {
    "devanagari": (0x0900, 0x097F),  # Hindi, Marathi
    "bengali": (0x0980, 0x09FF),
    "gurmukhi": (0x0A00, 0x0A7F),    # Punjabi
    "gujarati": (0x0A80, 0x0AFF),
    "odia": (0x0B00, 0x0B7F),
    "tamil": (0x0B80, 0x0BFF),
    "telugu": (0x0C00, 0x0C7F),
    "kannada": (0x0C80, 0x0CFF),
    "malayalam": (0x0D00, 0x0D7F),
}

# Common Hindi and Punjabi words typed in English letters. If a Latin-script
# message has 2 or more of these, it's treated as romanised Hindi/Punjabi
# (code-switched). Short words like "ho", "se", "ka" can show up by accident,
# which is why one match alone isn't enough.
ROMANISED_MARKERS = {
    # romanised Hindi / Hinglish
    "hai", "hain", "nahi", "nahin", "kya", "mera", "meri", "mere", "karo", "kar",
    "kab", "kyun", "kyon", "aap", "mujhe", "hoga", "raha", "rahi", "gaya", "gayi",
    "bhai", "paisa", "paise", "abhi", "kitna", "kitne", "wala", "wali", "ho", "se",
    "ko", "ka", "ki", "ke", "batao", "chahiye", "hua", "kaise", "kahan", "bhi",
    # romanised Punjabi
    "tusi", "tussi", "tuhada", "tuhadi", "menu", "mainu", "kiven", "kidan", "kithe",
    "kado", "hega", "hegi", "dasso", "daso", "nai", "vich", "da", "di", "de", "ne",
    "sanu", "assi", "ji", "karna", "paisa", "kinna", "kinne", "ohna",
}
HINGLISH_MARKERS = ROMANISED_MARKERS   # older name, still used below

# Prompt-injection phrases (English, Hindi, Punjabi). Any match => "attack",
# and the request gets a fixed refusal without calling a model.
ATTACK_CUES = [
    "ignore previous instructions", "ignore all previous", "ignore your instructions",
    "system prompt", "jailbreak", "developer mode", "you have no rules",
    "pretend you are not", "reveal your", "पिछले सभी निर्देश", "निर्देशों को अनदेखा",
    "ਪਿਛਲੀਆਂ ਹਦਾਇਤਾਂ", "ਸਿਸਟਮ ਪ੍ਰੌਂਪਟ", "सिस्टम प्रॉम्प्ट",
    # Role-play: getting the bot to act as bank staff and "approve" something
    # (tuning prompt u61). If the bot plays along, a screenshot of it could
    # pass for a real approval, so this is blocked outright.
    "you are now the", "you are now a ", "you are now my", "act as the", "act as a ",
    "act as my", "pretend to be", "pretend you are", "roleplay as", "role-play as", "role play as",
    "you are the bank manager", "as the bank manager", "as a bank manager",
    "अब तुम", "तुम अब", "अब आप बैंक", "बनकर", "ਤੁਸੀਂ ਹੁਣ", "ਹੁਣ ਤੁਸੀਂ", "ਬਣ ਕੇ",
    "ab tum", "tum ab", "ab aap bank",
    # Asking for other customers' data or internal data, often while claiming
    # to be staff (like prompt u64).
    "kisi bhi customer ka", "any customer's", "other customers'", "another customer's",
    "दूसरे ग्राहकों", "किसी भी ग्राहक का", "ਕਿਸੇ ਵੀ ਗਾਹਕ ਦਾ", "ਦੂਜੇ ਗਾਹਕਾਂ",
]

# Words that suggest reasoning, a calculation or a judgement call => "hard".
# These are substring matches, so "eligib" covers eligible / eligibility and
# "restructur" covers restructure / restructuring.
HARD_CUES = [
    "why", "explain", "calculate", "compute", "compare", "eligib", "comply",
    "compliance", "regulation", "legal", "policy says",
    "step by step", "should i", "which is better", "dispute", "penalty", "pro-rata",
    "pro rata", "interest", "restructur", "reason",
    # Hindi: why, calculation, eligible, rule, interest, account/sum, compare
    "क्यों", "गणना", "पात्र", "नियम", "ब्याज", "हिसाब", "तुलना",
    # Punjabi: why, eligible, account/sum, interest, rule
    "ਕਿਉਂ", "ਯੋਗ", "ਹਿਸਾਬ", "ਵਿਆਜ", "ਨਿਯਮ",
    # romanised Hindi / Punjabi: interest, account/sum, eligible, why
    "byaj", "byaaj", "vyaj", "viaj", "hisab", "hisaab", "patr", "yog ", "kyun", "kiun",
    # other Indic languages (router supports them; not in the test set)
    "ஏன்", "தகுதி", "கணக்கிட",            # Tamil: why, eligibility, calculate
    "ఎందుకు", "అర్హత",                    # Telugu: why, eligibility
    "কেন", "যোগ্য",                       # Bengali: why, eligible
    "पात्रता",                            # Marathi/Hindi: eligibility
]

# Compliance questions: did the agent read the disclosure, is this allowed
# under RBI/TRAI/SEBI rules, was consent taken, was something mis-sold...
# Getting one of these wrong means a missed compliance issue, which is the
# most expensive mistake for a bank. So they always go to the strongest model
# (GLM-5.3), whatever the language. In the live 4-model comparison only Flash
# and GLM-5.3 caught the tricky disclosure case.
COMPLIANCE_CUES = [
    "compliance", "comply", "disclosure", "disclos", "recorded", "record ho",
    "consent", "mis-sell", "missell", "regulation",
    "fair practice", "counts only if",
    "अनुपालन", "रिकॉर्ड", "सहमति", "ਰਿਕਾਰਡ", "ਸਹਿਮਤੀ",
]

# Regulator names are matched as whole words only. Otherwise "trai" would
# match "straight" or "training".
# KYC is left out on purpose: "update my KYC" is a routine request, and
# sending it to GLM-5.3 would just waste money.
ABBREV_COMPLIANCE = {"rbi", "sebi", "trai", "irdai", "npci"}
ABBREV_RE = re.compile(r"\b(" + "|".join(sorted(ABBREV_COMPLIANCE)) + r")\b")

# Language tasks: translate, summarise, write or draft a reply.
# In the live comparison (2026-11-18) sarvam-105b-conversations passed all of
# these, much cheaper and faster than the others, so they get their own rule.
# "draft a reply" used to be a hard cue. It was moved here; a draft that needs
# real judgement still goes hard through other cues (RBI, penalty, dispute...).
LANGUAGE_TASK_CUES = [
    "translate", "translation", "summar", "draft",
    "अनुवाद", "सार ", "सार:", "जवाब लिखिए", "जवाब लिखें", "जवाब लिखो",
    "ਅਨੁਵਾਦ", "ਸਾਰ ", "ਸਾਰ:", "ਜਵਾਬ ਲਿਖੋ",
]

# Words that suggest a short, mechanical task (label, tag, extract) => "simple".
SIMPLE_CUES = [
    "classify", "categorise", "categorize", "label", "tag ", "extract", "intent",
    "sentiment", "yes or no", "return json", "which category", "pick one",
    "one word", "detect language", "वर्गीकृत", "श्रेणी", "ਸ਼੍ਰੇਣੀ",
]

# A clear labelling / extraction instruction needs both a task verb
# ("classify", "extract") and a strict output format ("return only the label",
# "as JSON"). The verb is only looked for before "Message:", i.e. in the
# instruction and not in the customer text. Prompts like this are labelling
# jobs no matter what the customer's message says.
LABEL_TASK_RE = re.compile(r"\b(classify|categori[sz]e|label|tag this|extract)\b|वर्गीकृत|श्रेणी|ਸ਼੍ਰੇਣੀ")
LABEL_FORMAT_RE = re.compile(r"return only|only the label|return json|as json|only json|sirf json|केवल json|ਸਿਰਫ json")

# Sensitive numbers to hide before any model sees the text:
# card = 13-19 digits (spaces/dashes allowed), OTP/PIN = 4-8 digits just after
# the word, Aadhaar = 12 digits in groups of 4.
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
OTP_RE = re.compile(r"(?i)(otp|ओटीपी|pin)\D{0,12}(\d{4,8})")
AADHAAR_RE = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")


@dataclass
class Classification:
    language: str            # "en" | "indic" | "code_switched"
    scripts: list
    est_input_tokens: int
    is_junk: bool
    is_attack: bool
    hard_cues: list = field(default_factory=list)
    simple_cues: list = field(default_factory=list)
    language_task_cues: list = field(default_factory=list)   # translate / summarise / reply
    compliance_cues: list = field(default_factory=list)      # disclosure / RBI / consent...
    label_instruction: bool = False                           # "Classify ... return only the label" style task
    overhead_ms: float = 0.0
    router_tokens: int = 0   # tokens the router itself used (always 0, it's rule-based)


def mask_pii(text: str) -> tuple[str, int]:
    """Hide card numbers, OTPs and Aadhaar numbers before any model sees them.
    Used on typed text and on voice transcripts.
    Returns (masked_text, number_of_masks)."""
    n = 0
    def sub(rx, repl, s):
        nonlocal n
        s2, k = rx.subn(repl, s)
        n += k
        return s2
    text = sub(OTP_RE, lambda m: m.group(1) + " [OTP]", text)
    text = sub(CARD_RE, "[CARD]", text)
    text = sub(AADHAAR_RE, "[AADHAAR]", text)
    return text, n


def _scripts(text: str) -> dict:
    """Count how many characters of each Indic script appear in the text."""
    counts = {}
    for ch in text:
        cp = ord(ch)
        for name, (lo, hi) in INDIC_RANGES.items():
            if lo <= cp <= hi:
                counts[name] = counts.get(name, 0) + 1
                break
    return counts


def estimate_tokens(text: str) -> int:
    """Rough token count: about 4 characters per token for English, about 2.5
    for Indic scripts (most tokenizers split them into smaller pieces).
    Only used in mock mode; real runs use the counts the API sends back."""
    indic = sum(_scripts(text).values())
    latin = len(text) - indic
    return max(1, int(latin / 4 + indic / 2.5))


def _is_junk(text: str) -> bool:
    """True for messages with nothing to answer: too short, or keyboard mashing."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 3:
        return True                       # "??", "...", "ok"
    if _scripts(text):
        return False                      # Indic text is not junk
    words = re.findall(r"[a-zA-Z]+", text.lower())
    # Keyboard mashing like "asdfghjk qwrtpl": words of 5+ letters that are
    # nearly all consonants, or contain a run of neighbouring keys.
    # If more than half the words look like that, it's junk.
    rows = ("qwert", "werty", "asdf", "sdfg", "dfgh", "fghj", "ghjk", "hjkl", "zxcv", "xcvb")
    def mashy(w):
        vowels = len(re.findall(r"[aeiouy]", w))
        return len(w) >= 5 and (vowels / len(w) < 0.2 or any(r in w for r in rows))
    mash = [w for w in words if mashy(w)]
    return len(words) > 0 and len(mash) / len(words) > 0.5


def classify(text: str) -> Classification:
    t0 = time.perf_counter()
    low = text.lower()
    scripts = _scripts(text)
    indic_chars = sum(scripts.values())
    latin_words = re.findall(r"[a-zA-Z]+", low)
    hinglish_hits = sum(1 for w in latin_words if w in HINGLISH_MARKERS)

    # Language decision:
    #   Indic script + 3 or more English words  -> code_switched
    #   Indic script only                       -> indic
    #   English letters but 2+ Hindi/Punjabi words -> code_switched (romanised)
    #   anything else                           -> en
    if indic_chars and len(latin_words) >= 3:
        language = "code_switched"        # Indic script mixed with English words
    elif indic_chars:
        language = "indic"
    elif hinglish_hits >= 2:
        language = "code_switched"        # romanised Hindi
    else:
        language = "en"

    c = Classification(
        language=language,
        scripts=sorted(scripts),
        est_input_tokens=estimate_tokens(text),
        is_junk=_is_junk(text),
        is_attack=any(cue in low for cue in ATTACK_CUES),
        hard_cues=[cue for cue in HARD_CUES if cue in low] + ABBREV_RE.findall(low),
        simple_cues=[cue for cue in SIMPLE_CUES if cue in low],
        # "write ... reply" anywhere in the prompt also counts as a language task
        language_task_cues=[cue for cue in LANGUAGE_TASK_CUES if cue in low]
                           + (["write…reply"] if "write" in low and "reply" in low else []),
        compliance_cues=[cue for cue in COMPLIANCE_CUES if cue in low] + ABBREV_RE.findall(low),
        # task verb is checked only in the part before "message:"
        label_instruction=bool(LABEL_TASK_RE.search(low.split("message:")[0]) and LABEL_FORMAT_RE.search(low)),
    )
    c.overhead_ms = (time.perf_counter() - t0) * 1000
    return c
