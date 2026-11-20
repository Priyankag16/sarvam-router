# Tuning-set run: live Sarvam API, 36 prompts (2026-11-18)

**Setup:**
- **Prompts:** 36 from `tuning set.xlsx`, converted to `data/tuning.jsonl`. The sheet has 37 rows including the header.
- **Router config:** router only, using the BFSI tenant policy and the classifier as it stood. The four proposed classifier fixes were **not** applied.
- **API:** live, `https://api.sarvam.ai/v2/chat/completions`.
- **Judge:** scored against the spreadsheet rubrics (`rubric_scores.jsonl`). The author's blind scores are pending (`author_scores_TO_FILL.csv`).

This is the **tuning** set. Fixing what it reveals is legitimate. The 40-prompt test set stays held out for the final numbers.

## Headline

| | Result |
|---|---|
| Answers passing the rubric | **29 / 36 (81%)** |
| Routing check (no hard→cheap, no easy→GLM-5.3) | **34 / 36**. Both misses are compliance checks sent to the cheap tier |
| Human-review flag matches the sheet | **27 / 36**. **0 of 5** required flags raised; 4 false flags |
| Total cost | **₹1.07** (GLM-5.3: 2 requests, ₹0.38) |
| Latency p50 / p95 | 2.7 s / **25.4 s**. p95 is driven by 4 first-attempt timeouts |
| Reasoning tokens as share of output | **90%** |

Pass rate by language:

| Language | Pass |
|---|---|
| English | 12/13 |
| Hindi | 6/7 |
| Hinglish | 6/8 |
| Romanised Punjabi | 3/3 |
| **Punjabi (Gurmukhi)** | **2/5** |

Punjabi is the weakest. All three Punjabi failures were on Sarvam-105B, and they were instruction-following or token-budget failures, not comprehension failures (see C and D).

## What went well
- **Classification and extraction: 10/11 across all languages.** Hindi and Punjabi dates were converted to "5 Nov" and "22 Sep"; the larger of two payments was picked correctly; sarcasm was read correctly.
- **Reasoning was right whenever an answer came back.**
  - Both GLM-5.3 comparisons (u19, u21) were correct, including the case where compound interest at a lower rate beats simple interest.
  - Sarvam-105B got the Hindi loan comparison and the 0%-EMI edge case right.
- **Long-context "needle" questions passed in Hindi and English.** The model found the planted fact in a ~3,000-token transcript and applied the later correction (7 pm, not 5 pm).
- **The guards held against false positives.**
  - "bal?" was *not* treated as junk.
  - "Ignore my previous message, I meant savings…" was *not* treated as an attack.
  - "!!!! ???? ...." got the template reply for ₹0.
- **The prompt injection was refused** (u31), with a legitimate path offered and nothing revealed.
- **Drafted replies in Hindi, Punjabi and English** were polite, stuck to the given facts, and made no extra promises.

## What failed, by root cause

### A. Router under-routed compliance checks (u35, u36). Highest priority
Both compliance prompts went to **R4-simple, 105B at low effort**. The only cue the classifier saw was the output format "yes or no", and there was no compliance cue. u36 then got the compliance finding **wrong**: `disclosure_read: yes` when the answer is *no*. A missed compliance finding is the costliest kind of error for a bank.

**Fix:**
- Add compliance cues: disclosure, recorded / record ho, consent, mis-sell, "counts only if".
- Never let a *format* cue ("yes or no", "return JSON") make a *judgement* task simple.

### B. The human-review rule is wrong in kind: 0/5 recall, 4 false positives
R6 matches keywords in the **prompt** ("loan", "complaint"). The sheet's rules depend on **what the answer does**:
- **HR1:** it commits the bank to a timeline
- **HR3:** it replies to a complaint
- **HR4:** it is a compliance finding

| Error | Cases | Why |
|---|---|---|
| Missed | u08, u09, u10, u33, u36 | No keyword present |
| False flag | u17, u22, u27, u31 | "loan" or "complaint" appeared in a translation, a calculation, a transcript, and an *attack*. The rubric says an attack must **not** be escalated |

**Fix:** decide R6 from the task type plus the output.
- Customer-facing drafted replies about delays or complaints → review.
- Anything committing to a date or timeline → review.
- A compliance answer with `no` → review.
- Never flag classification or extraction, refusals, or calculations.
- Match keywords against the question line only, not the transcript.

### C. Empty answer counted as success (u22)
Sarvam-105B at **high** effort spent all 4,000 tokens reasoning on the Punjabi EMI question and returned **no text**. The status was still `ok`, so no fallback fired, and it cost ₹0.10 and 18 s.

**Fix:**
- Treat empty content (or `finish_reason = length`) as a failure, so the ladder escalates.
- Consider default rather than high effort for Indic calculations, or a larger token budget.

### D. Model instruction-following failures on Sarvam-105B (routing was right)

| Case | Problem |
|---|---|
| u02 | Returned the Hindi word "शिकायत" instead of the English label `complaint` |
| u15 | Asked to translate Punjabi to English, it echoed the Punjabi back |
| u17 | Gave several Punjabi variants with English commentary, and dropped "loan" |
| u30 | Didn't recognise "bal?" as a balance query |

**Fix:** a short system prompt per route. For example:
- "Return exactly one of the given labels, in English."
- "Translate only; output only the translation in the target language."
- "You are a bank support assistant; short inputs are likely banking requests."

These cost almost nothing and target the Punjabi failures directly. Translation is also an argument for bringing forward the deferred translation route.

### E. Voice
- **u34 failed.** The "[AUDIO … noise]" placeholder was answered in English, as if it were an audio file. It should have been a confirmation in Hinglish: "card block karna hai?"
- **u33 was right but far too long** for a voice turn.

**Fix:**
- A voice system prompt: two short sentences, in the caller's language.
- A **low-confidence speech-to-text → confirm-intent** template rule, so the router never acts on a garbled transcript.

### F. Latency: timeouts are expensive
**4 of 35 first attempts timed out** on Sarvam-105B (u02, u30, u32, u36). Each waited the full **20 s** before an immediate retry succeeded. That alone sets p95 at 25 s; first-attempt successes have p95 10 s.

**Fix:**
- Scale the timeout to the expected output, e.g. 8 s for labels and short replies.
- On a timeout, skip the same-model retry and go **straight to the next rung**: Flash, which in the earlier connection check answered in about 0.5 s.

## The cost finding that changes a design decision
**Reasoning tokens dominate the bill.** They are 90% of output tokens and billed at the output rate.

**Effort "low" barely limits them on Sarvam-105B.** It averaged **421 reasoning tokens per call**, up to 1,146, to produce one-word labels. The mock assumed 40.

| Simple tasks (R4, 13 requests) | Cost |
|---|---|
| Actual: Sarvam-105B, low effort | ₹0.171 |
| Same visible output on GLM-5.3 Flash, low effort (*estimate*, 0 reasoning tokens as seen in the earlier connection check) | ≈ ₹0.019 |
| Same visible output on sarvam-105b-conversations (*estimate*, no reasoning) | ≈ ₹0.013 |

**What this changes:**
- **The per-token list price was misleading.** Simple → Sarvam-105B was chosen because its token price is lowest, but the hidden reasoning makes it the most expensive option for labels.
- **The fix is likely simple → 105b-conversations or Flash-low.** Both look roughly 10× cheaper and faster.
- **This needs measuring before the rulebook changes:** an A/B run of the 13 simple prompts on all three options, costing under ₹0.10.
- **The mock assumptions for Part 2 also need updating.** GLM-5.3 averaged 260 reasoning tokens, not the 500 assumed; Sarvam-105B low averaged 421, not 40.

## Recommended tuning changes, in priority order
1. **Treat empty output as a failure** (C). One-line fix; prevents silent blank answers.
2. **Add compliance cues, and stop format cues making judgement tasks simple** (A).
3. **Redesign R6 human review** by task type plus output, not keywords (B).
4. **Shorter timeouts; skip to the next rung on a timeout** (F).
5. **Add a system prompt per route:** labels, translation, voice brevity and language (D, E). Add a low-confidence speech-to-text confirm rule.
6. **Run the simple-tier A/B** (105B-low vs Flash-low vs conversations), then decide the cheap tier on *measured* cost and quality.
7. **Apply the earlier classifier fixes**, widened by this run: numeric reasoning; questions judged by the instruction or question line, not the transcript (u26 was over-routed by "ब्याज" inside a transcript); weak cues need backing.

Then rerun this tuning set and compare. When the rules are frozen, run the held-out 40-prompt test set live, with baselines, for the README numbers.
