"""
Model calls: the real API call, a mock mode for running without a key,
and the fallback ladder.

How the ladder works (run_ladder):
    try the first model -> on timeout/error, retry once on the same model
                        -> still failing, or bad JSON / an odd refusal: move up a step
    at most 2 escalations (3 models), then give up.

Failed attempts still cost money and time, so their tokens and latency are
added to the request's totals. Otherwise fallbacks would look free.

All four models are served from one Sarvam endpoint with one key
(see config/models.yaml).

Mock mode (--mock) fakes each call, but deterministically: the same prompt,
model and attempt always give the same result. The numbers are assumptions,
not measurements:
  latency  = time to first token + output tokens / tokens per second
  tokens   = estimated input + expected answer length + reasoning tokens
  quality  = a rough table of model x difficulty x language, plus some noise
  failures = small random timeout / bad-format rates, plus forced faults from
             the `inject` field in the test set, so the ladder gets exercised
With SARVAM_API_KEY set and --mock dropped, the same code makes real calls.
"""
import hashlib
import json
import os
import random
import time

from .classify import estimate_tokens

# ---- mock-mode assumptions (every mock output is labelled "mock") ----
# (time to first token in seconds, tokens per second)
SPEED = {
    "glm-5.3-flash": (0.30, 160),
    "sarvam-105b-conversations": (0.25, 110),
    "sarvam-105b": (0.50, 70),
    "glm-5.3": (0.90, 55),
}
# chance a call times out or returns malformed output
FAIL_P = {"glm-5.3-flash": 0.03, "sarvam-105b-conversations": 0.03, "sarvam-105b": 0.03, "glm-5.3": 0.04}

# Average quality (1-5) by model and difficulty. These are the guesses the
# live run was meant to check: all models do fine on easy work, GLM-5.3 is
# best on hard English, and Sarvam-105B does better than GLM on hard Indic text.
QUALITY = {               # easy  medium  hard
    "glm-5.3-flash":             (4.4, 3.7, 2.8),
    "sarvam-105b-conversations": (4.4, 3.9, 3.1),
    "sarvam-105b":               (4.5, 4.2, 3.6),
    "glm-5.3":                   (4.7, 4.5, 4.5),
}
EFFORT_BONUS = {"low": -0.15, "default": 0.0, "high": 0.35}   # medium/hard only
# GLM drops a bit on Indic / code-switched text, Sarvam gains a little
INDIC_ADJ = {"glm-5.3-flash": -0.45, "glm-5.3": -0.45,
             "sarvam-105b": +0.10, "sarvam-105b-conversations": +0.10}
DIFF_IDX = {"easy": 0, "medium": 1, "hard": 2}


def _rng(*parts) -> random.Random:
    """Random generator seeded from the call details, so mock runs repeat exactly."""
    seed = int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)
    return random.Random(seed)


def cost_inr(model: str, tin: int, tout: int, cfg: dict) -> float:
    """₹ cost of one call at Sarvam list price. Reasoning tokens are inside tout."""
    m = cfg["models"][model]
    return tin / 1e6 * m["in_inr_per_m"] + tout / 1e6 * m["out_inr_per_m"]


def mock_call(req: dict, prompt: str, model: str, effort: str, attempt: int, cfg: dict) -> dict:
    r = _rng(req["id"], model, effort, attempt)
    ttft, tps = SPEED[model]
    tin = estimate_tokens(prompt) + 60                         # + system prompt
    reasoning = cfg["reasoning_tokens"][model][effort]
    visible = int(req.get("out_tokens", 150) * r.uniform(0.85, 1.15))
    tout = visible + reasoning
    latency = (ttft + tout / tps) * r.uniform(0.85, 1.35)      # long-tail jitter

    # failures: forced on the first attempt (to exercise the ladder) or random
    inject = req.get("inject")
    status = "ok"
    if inject == "timeout" and attempt == 0:
        status = "timeout"
    elif inject == "bad_json" and attempt == 0:
        status = "bad_format"
    elif r.random() < FAIL_P[model]:
        status = r.choice(["timeout", "bad_format"])
    if status == "timeout":
        latency = cfg["models"][model]["timeout_s"]            # we waited the full budget
        tout = 0                                                # no output billed

    d = DIFF_IDX[req["difficulty"]]
    q = QUALITY[model][d] + (EFFORT_BONUS[effort] if d > 0 else 0)
    if req["lang"] != "en":
        q += INDIC_ADJ[model]
    q = max(1.0, min(5.0, q + r.gauss(0, 0.3)))
    return {"status": status, "text": f"[mock answer from {model}/{effort}]", "in_tokens": tin,
            "out_tokens": tout, "latency_s": latency, "mock_quality": round(q, 2)}


def _ssl_context():
    """Use the OS certificate store for HTTPS if truststore is installed.
    Antivirus tools and office proxies often re-sign HTTPS traffic with a
    certificate Windows trusts but Python doesn't. This keeps verification on
    instead of having to switch it off."""
    try:
        import ssl
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return True


def real_call(req: dict, prompt: str, model: str, effort: str, attempt: int, cfg: dict) -> dict:
    """One chat-completions call to the Sarvam endpoint (same format for all 4 models)."""
    import httpx
    ep = cfg["endpoint"]
    url = os.environ.get(ep["url_env"]) or ep["url"]
    key = os.environ[ep["key_env"]]
    body = {"model": cfg["models"][model]["api_model"],
            "messages": ([{"role": "system", "content": req["_instruction"]}] if req.get("_instruction") else [])
                        + [{"role": "user", "content": prompt}],
            "max_tokens": ep.get("max_tokens", 4000)}
    if effort != "default":
        body["reasoning_effort"] = effort
    if req.get("_temperature") is not None:
        body["temperature"] = req["_temperature"]
    t0 = time.perf_counter()
    try:
        resp = httpx.post(url, json=body, timeout=cfg["models"][model]["timeout_s"],
                          headers={ep["auth_header"]: key}, verify=_ssl_context())
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        return {"status": "timeout", "text": "", "in_tokens": 0, "out_tokens": 0,
                "latency_s": time.perf_counter() - t0}
    except Exception as e:  # HTTP 4xx/5xx, unreadable response
        return {"status": "error", "text": str(e)[:200], "in_tokens": 0, "out_tokens": 0,
                "latency_s": time.perf_counter() - t0}
    text = data["choices"][0]["message"].get("content") or ""
    usage = data.get("usage", {})
    status = "ok"
    # A JSON task that doesn't return valid JSON counts as a failure, so the
    # ladder moves to the next model.
    if req.get("expects_json"):
        try:
            json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
        except ValueError:
            status = "bad_format"
    if req.get("category") != "attack" and any(
            p in text.lower() for p in ("i can't help", "i cannot help", "i'm unable to")):
        status = "refusal"            # refused a normal request, try another model
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    return {"status": status, "text": text, "in_tokens": usage.get("prompt_tokens", 0),
            "out_tokens": usage.get("completion_tokens", 0), "reasoning_tokens": reasoning,
            "latency_s": time.perf_counter() - t0}


def run_ladder(req: dict, prompt: str, ladder: list, cfg: dict, mock: bool) -> dict:
    """Try each model on the ladder in turn. Returns the final answer and
    every attempt made, so the log shows what happened."""
    call = mock_call if mock else real_call
    attempts, total_cost, total_lat = [], 0.0, 0.0
    for step in ladder[: cfg["max_escalations"] + 1]:
        for _retry in (0, 1):                      # one retry, for timeout/error only
            res = call(req, prompt, step.model, step.effort, len(attempts), cfg)
            c = cost_inr(step.model, res["in_tokens"], res["out_tokens"], cfg)
            total_cost += c
            total_lat += res["latency_s"]
            attempts.append({"model": step.model, "effort": step.effort, "status": res["status"],
                             "in_tokens": res["in_tokens"], "out_tokens": res["out_tokens"],
                             "reasoning_tokens": res.get("reasoning_tokens", 0),
                             "cost_inr": round(c, 6), "latency_s": round(res["latency_s"], 3)})
            if res["status"] == "ok":
                return {"final": res, "model": step.model, "effort": step.effort, "attempts": attempts,
                        "cost_inr": total_cost, "latency_s": total_lat, "gave_up": False}
            if res["status"] in ("bad_format", "refusal"):
                break                              # retrying won't fix this, go up a step
    return {"final": None, "model": None, "effort": None, "attempts": attempts,
            "cost_inr": total_cost, "latency_s": total_lat, "gave_up": True}
