"""
Run MP4 / audio files end to end: speech-to-text -> router -> model.

    python run_audio.py path/to/clips            # every .mp4 .m4a .wav .mp3 .aac .ogg in the folder
    python run_audio.py clip1.mp4 clip2.mp4 --tenant bfsi --channel voice_live

For each file:
  1. router/stt.py pulls out the audio, transcribes it with Saaras (codemix)
     and masks card numbers / OTPs / Aadhaar.
  2. Confidence check: if the transcript is shaky (empty, under 3 words, or
     low language probability), the bot doesn't act on it. It asks a short
     confirmation question in the caller's language ("क्या आप अपना कार्ड ब्लॉक
     करवाना चाहते हैं?") and no model is called. This was added after the
     tuning run, where garbled audio got confidently wrong answers (u34/u70).
  3. Otherwise the transcript goes through the normal router, same as text,
     on the voice_live channel.
  4. One log row per file goes to results/audio/audio_runs.jsonl: transcript,
     detected language and probability, rule, model, answer, STT time, model
     time, total time (what the caller actually waits), costs and the
     human-review flag.
The 1.5 s voice target is checked against the total time.
"""
import argparse
import json
import pathlib
import time

from dotenv import load_dotenv

from router.call import run_ladder
from router.classify import classify
from router.rules import needs_human, route
from router.stt import confirmation_reply, low_confidence, transcribe
from run_eval import load_cfg

ROOT = pathlib.Path(__file__).parent
AUDIO_EXT = {".mp4", ".m4a", ".wav", ".mp3", ".aac", ".ogg", ".webm", ".flac"}


def collect(paths):
    """Expand folders into their audio files and keep only supported extensions."""
    files = []
    for p in map(pathlib.Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in AUDIO_EXT)
        elif p.suffix.lower() in AUDIO_EXT:
            files.append(p)
    return files


def run_file(path, cfg, tenant, channel, mode):
    stt = transcribe(str(path), cfg, mode=mode)
    row = {k: v for k, v in stt.items()}
    req = {"id": path.stem, "tenant": tenant["tenant"], "channel": channel,
           "category": "voice", "prompt": stt["transcript"]}
    why_low = low_confidence(stt, cfg)
    t0 = time.perf_counter()
    if why_low:
        # Unsure what was said: confirm with the caller instead of acting.
        intent, reply = confirmation_reply(stt)
        row.update({"rule_id": "R0-stt-confirm", "reason": f"low-confidence transcript: {why_low}; "
                    f"confirm '{intent}' before acting", "model": None, "answer": reply, "attempts": [],
                    "model_cost_inr": 0.0, "model_latency_ms": 0.0, "router_overhead_ms": 0.0,
                    "human_review": None})
    else:
        c = classify(stt["transcript"])
        d = route(req, c, tenant)
        if d.template is not None:
            res = {"final": None, "model": None, "attempts": [], "cost_inr": 0.0, "latency_s": 0.0}
            answer = d.template
        else:
            req = {**req, "_instruction": d.instruction, "_temperature": d.temperature}
            res = run_ladder(req, stt["transcript"], d.ladder, cfg, mock=False)
            answer = (res["final"] or {}).get("text") if res.get("final") else None
        row.update({"rule_id": d.rule_id, "reason": d.reason, "detected_lang": c.language,
                    "model": res["model"], "answer": answer, "attempts": res["attempts"],
                    "holding_phrase": d.holding_phrase,
                    "model_cost_inr": round(res["cost_inr"], 6),
                    "model_latency_ms": round(res["latency_s"] * 1000, 1),
                    "router_overhead_ms": round(c.overhead_ms, 3),
                    "human_review": needs_human(req, stt["transcript"], answer, d.rule_id, tenant)})
    row["total_latency_ms"] = round(row["stt_ms"] + row["router_overhead_ms"] + row["model_latency_ms"], 1)
    row["total_cost_inr"] = round(row["stt_cost_inr"] + row["model_cost_inr"], 6)
    row["meets_voice_target"] = row["total_latency_ms"] <= tenant.get("live_voice_p95_ms", 1500)
    row["gate_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="audio/video files or folders")
    ap.add_argument("--tenant", default="bfsi", help="config/tenants/<name>.yaml")
    ap.add_argument("--channel", default="voice_live", choices=["voice_live", "batch"])
    ap.add_argument("--mode", default=None, help="Saaras mode: codemix (default), transcribe, translate, verbatim")
    ap.add_argument("--out", default="results/audio")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    cfg, tenants = load_cfg()
    tenant = tenants[args.tenant]
    files = collect(args.paths)
    if not files:
        raise SystemExit("No audio/video files found.")
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with open(out / "audio_runs.jsonl", "a", encoding="utf8") as f:
        for p in files:
            try:
                row = run_file(p, cfg, tenant, args.channel, args.mode)
            except Exception as e:  # log the failure and carry on with the next file
                row = {"file": str(p), "error": f"{type(e).__name__}: {str(e)[:300]}"}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows.append(row)
            if "error" in row:
                print(f"\n=== {p.name}: ERROR {row['error']}")
                continue
            print(f"\n=== {p.name}  ({row['audio_seconds']} s audio, {row['chunks']} chunk(s))")
            print(f"  transcript : {row['transcript']}")
            print(f"  language   : {row['stt_language']} (p={row['stt_language_probability']})  pii masked: {row['pii_masked']}")
            print(f"  route      : {row['rule_id']} -> {row['model']}   ({row['reason'][:90]})")
            print(f"  answer     : {(row['answer'] or '(none)')[:300]}")
            print(f"  latency    : STT {row['stt_ms']:.0f} ms + model {row['model_latency_ms']:.0f} ms = "
                  f"TOTAL {row['total_latency_ms']:.0f} ms  (target {tenant.get('live_voice_p95_ms')} ms: "
                  f"{'OK' if row['meets_voice_target'] else 'MISSED'})")
            print(f"  cost       : STT ₹{row['stt_cost_inr']:.4f} + model ₹{row['model_cost_inr']:.4f}; "
                  f"human review: {row['human_review']}")
    print(f"\nlogged {len(rows)} file(s) to {out / 'audio_runs.jsonl'}")


if __name__ == "__main__":
    main()
