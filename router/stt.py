"""
Speech-to-text: turns an MP4 / M4A / WAV / MP3 file into a masked transcript
using Sarvam's Saaras model, before the router sees it.

Steps for one file:
  1. ffmpeg (shipped with the imageio-ffmpeg package) pulls out the audio,
     drops any video, and converts it to 16 kHz mono WAV, which is what
     Sarvam recommends. Phone recordings and video files both work.
  2. The Sarvam API takes at most 30 seconds of audio per request, so longer
     audio is cut into 29-second pieces, sent one by one and joined back up.
  3. Each piece goes to POST https://api.sarvam.ai/speech-to-text with the
     same API key as the chat models:
        model = saaras:v4, mode = codemix, language_code = unknown (auto-detect)
     "codemix" keeps Hindi/Punjabi words in their own script and English words
     in English (e.g. "मेरा card block करो"). That's how people actually talk,
     and it's what the router's language detection expects.
  4. Card numbers, OTPs and Aadhaar numbers are masked (classify.mask_pii)
     before the transcript is used anywhere.
  5. Time and cost are recorded. The caller has to wait for transcription too,
     so it's added to the total latency. Saaras costs ₹0.49 per minute of audio.

Saaras gives a language_probability (0-1) but no per-word confidence. A
transcript counts as low confidence (so the bot asks the caller to confirm
instead of acting) when that probability is low, the transcript is very
short, or it's mostly noise markers. See low_confidence().
"""
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from .classify import mask_pii

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def audio_duration_s(path: str) -> float:
    """Read the duration from ffmpeg's header output (no ffprobe needed)."""
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                       capture_output=True, text=True, encoding="utf8", errors="replace")
    m = DURATION_RE.search(p.stderr)
    if not m:
        raise ValueError(f"could not read duration of {path}: {p.stderr[-300:]}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def to_wav_chunks(path: str, workdir: str, chunk_s: int) -> list[str]:
    """Extract the audio as 16 kHz mono WAV, split into chunk_s-second pieces."""
    # -vn drops video, -ac 1 = mono, -ar 16000 = 16 kHz, segment = split into pieces
    pattern = os.path.join(workdir, "chunk_%03d.wav")
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
           "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
           "-f", "segment", "-segment_time", str(chunk_s), "-reset_timestamps", "1", pattern]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {path}: {p.stderr[-400:]}")
    return sorted(str(f) for f in Path(workdir).glob("chunk_*.wav"))


def _post_chunk(wav: str, cfg: dict, mode: str, language: str) -> dict:
    import httpx
    from .call import _ssl_context
    st = cfg["stt"]
    key = os.environ[cfg["endpoint"]["key_env"]]
    with open(wav, "rb") as fh:
        files = {"file": (Path(wav).name, fh, "audio/wav")}
        data = {"model": st["model"], "mode": mode, "language_code": language}
        r = httpx.post(st["url"], files=files, data=data, timeout=st.get("timeout_s", 30),
                       headers={cfg["endpoint"]["auth_header"]: key}, verify=_ssl_context())
    if r.status_code != 200:
        raise RuntimeError(f"Saaras HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def transcribe(path: str, cfg: dict, mode: str | None = None, language: str = "unknown") -> dict:
    """Transcribe one audio/video file. Returns transcript (masked) plus timing,
    cost, detected language and confidence fields for the log."""
    st = cfg["stt"]
    mode = mode or st["mode"]
    dur = audio_duration_s(path)
    t0 = time.perf_counter()
    parts, langs, probs, req_ids = [], [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        t_conv = time.perf_counter()
        chunks = to_wav_chunks(path, tmp, st["max_chunk_s"])
        convert_ms = (time.perf_counter() - t_conv) * 1000
        for c in chunks:
            res = _post_chunk(c, cfg, mode, language)
            parts.append((res.get("transcript") or "").strip())
            langs.append(res.get("language_code"))
            if res.get("language_probability") is not None:
                probs.append(float(res["language_probability"]))
            req_ids.append(res.get("request_id"))
    raw = " ".join(p for p in parts if p)
    masked, n_masked = mask_pii(raw)
    return {
        "file": str(path), "audio_seconds": round(dur, 2), "chunks": len(parts),
        "stt_model": st["model"], "stt_mode": mode,
        "transcript": masked, "pii_masked": n_masked,
        "stt_language": next((l for l in langs if l), None),
        # take the lowest chunk score, so one bad piece marks the whole thing unsure
        "stt_language_probability": min(probs) if probs else None,
        "stt_ms": round((time.perf_counter() - t0) * 1000, 1),
        "stt_convert_ms": round(convert_ms, 1),
        "stt_cost_inr": round(dur / 60 * st["price_inr_per_min"], 5),
        "stt_request_ids": req_ids,
    }


# Things the transcriber writes for non-speech: [noise], (inaudible), "..."
NOISE_RE = re.compile(r"\[[^\]]*\]|\(.*?\)|\.\.\.|…")


def low_confidence(stt: dict, cfg: dict) -> str | None:
    """Return the reason if the transcript is too unreliable to act on, else None.
    Thresholds (min_words, min_language_probability) are in config/models.yaml."""
    th = cfg["stt"]
    text = NOISE_RE.sub(" ", stt["transcript"])
    # word characters plus the whole Indic Unicode range (Devanagari to Malayalam)
    words = re.findall(r"[\wऀ-ൿ]+", text)
    if not words:
        return "empty transcript"
    if len(words) < th["min_words"]:
        return f"only {len(words)} word(s) recognised"
    p = stt.get("stt_language_probability")
    if p is not None and p < th["min_language_probability"]:
        return f"low language confidence ({p:.2f})"
    return None


# Short confirmation questions in the caller's language. If we can make out a
# likely intent from the bits we heard, we ask about that one; otherwise we
# just ask them to repeat. "default" is used when the language is unclear.
CONFIRM = {
    "card_block": {"hi-IN": "क्या आप अपना कार्ड ब्लॉक करवाना चाहते हैं? हाँ या ना बताइए।",
                   "pa-IN": "ਕੀ ਤੁਸੀਂ ਆਪਣਾ ਕਾਰਡ ਬਲੌਕ ਕਰਵਾਉਣਾ ਚਾਹੁੰਦੇ ਹੋ? ਹਾਂ ਜਾਂ ਨਾ ਦੱਸੋ।",
                   "en-IN": "Do you want to block your card? Please say yes or no.",
                   "default": "Kya aap apna card block karwana chahte hain? Haan ya na bataiye."},
    "balance": {"hi-IN": "क्या आप अपने खाते का बैलेंस जानना चाहते हैं?",
                "pa-IN": "ਕੀ ਤੁਸੀਂ ਆਪਣੇ ਖਾਤੇ ਦਾ ਬੈਲੇਂਸ ਜਾਣਨਾ ਚਾਹੁੰਦੇ ਹੋ?",
                "en-IN": "Do you want to know your account balance?",
                "default": "Kya aap apna account balance jaanna chahte hain?"},
    "repeat": {"hi-IN": "माफ़ कीजिए, आवाज़ साफ़ नहीं आई। क्या आप दोबारा बता सकते हैं?",
               "pa-IN": "ਮਾਫ਼ ਕਰਨਾ, ਆਵਾਜ਼ ਸਾਫ਼ ਨਹੀਂ ਆਈ। ਕੀ ਤੁਸੀਂ ਦੁਬਾਰਾ ਦੱਸ ਸਕਦੇ ਹੋ?",
               "en-IN": "Sorry, I couldn't hear that clearly. Could you say it again?",
               "default": "Maaf kijiye, awaaz saaf nahi aayi. Kya aap dobara bata sakte hain?"},
}
# Words that point to each intent, in English, Hindi, Punjabi and romanised forms.
INTENT_HINTS = {
    "card_block": ["block", "ब्लॉक", "ਬਲੌਕ", "band kar", "बंद"],
    "balance": ["balance", "बैलेंस", "ਬੈਲੇਂਸ", "kitna paisa", "कितना पैसा"],
}


def confirmation_reply(stt: dict) -> tuple[str, str]:
    """(intent_guess, reply text) for a low-confidence transcript."""
    low = stt["transcript"].lower()
    intent = next((k for k, hints in INTENT_HINTS.items() if any(h in low for h in hints)), "repeat")
    lang = stt.get("stt_language") if stt.get("stt_language") in ("hi-IN", "pa-IN", "en-IN") else "default"
    return intent, CONFIRM[intent][lang]
