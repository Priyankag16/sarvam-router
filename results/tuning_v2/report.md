# Live results: 75-prompt tuning set, router vs baselines (2026-11-18)

Live Sarvam API. Scoring: objective rubrics by script (25 prompts), the rest against the author's rubric with a written reason (50 prompts); pass = score >= the sheet's pass mark. Author's blind scores pending.

## 1. Baselines vs router

| Metric | Always-cheapest (conversations) | Always-frontier (GLM-5.3) | Router |
|---|---|---|---|
| Passed (of 75) | 63 | 61 | 68 |
| Avg score, % of max | 84% | 86% | 90% |
| Passed: hard prompts (of 15) | 12 | 11 | 14 |
| Passed: Hindi/Punjabi/Hinglish (of 59) | 50 | 47 | 54 |
| Passed: English (of 16) | 13 | 14 | 14 |
| Cost, 75 requests (₹) | 0.32 | 26.57 | 3.14 |
| p50 latency (s) | 0.3 | 3.0 | 0.3 |
| p95 latency (s) | 1.0 | 20.3 | 9.1 |
| p95 latency, live voice (s) | 1.3 | 26.7 | 0.9 |
| Reasoning share of output tokens | 0% | 83% | 71% |
| Blank answers (token budget spent reasoning) | 0 | 3 | 0 |
| Requests where a fallback fired | 0 | 0 | 2 |

Router vs always-frontier on these 75 prompts: **88% cheaper** (95% bootstrap range 78%–95%); passes 68 vs 61 (difference +7, range +0 to +14).

## 2. Passes by task type

| Task (n) | Cheapest | Frontier | Router |
|---|---|---|---|
| classification (20) | 16 | 15 | **17** |
| extraction (5) | 3 | **5** | **5** |
| drafting (5) | **5** | **5** | **5** |
| summary (5) | **5** | **5** | **5** |
| translation (10) | **10** | **10** | **10** |
| reasoning (10) | 8 | 7 | **9** |
| qa (10) | 9 | **10** | 9 |
| support_reply (5) | **3** | 0 | **3** |
| compliance (5) | 4 | 4 | **5** |

## 3. Passes by language

| Language (n) | Cheapest | Frontier | Router |
|---|---|---|---|
| en (16) | 13 | 14 | 14 |
| hi (19) | 18 | 16 | 19 |
| pa (18) | 15 | 15 | 17 |
| hinglish (16) | 13 | 12 | 14 |
| rom_pa (6) | 4 | 4 | 4 |

## 4. Where the router sent traffic

| Rule | Requests |
|---|---|
| R1-attack | 1 |
| R1-junk | 1 |
| R2-voice-easy | 5 |
| R3-hard-en | 3 |
| R3-hard-indic | 10 |
| R3c-compliance | 6 |
| R4-simple | 19 |
| R4b-language-task | 16 |
| R5-default | 14 |

| Final model | Requests |
|---|---|
| sarvam-105b-conversations | 54 |
| glm-5.3 | 9 |
| sarvam-105b | 8 |
| glm-5.3-flash | 2 |
| template (no model) | 2 |

Under-routed (hard prompt not on a hard rule): ['u39']. Over-routed (easy prompt answered by GLM-5.3): none.
Human review: sheet expects 10; router flagged 9; correct flags 0, missed ['u11', 'u12', 'u13', 'u14', 'u15', 'u39', 'u66', 'u72', 'u74', 'u75'], false ['u04', 'u31', 'u32', 'u41', 'u43', 'u44', 'u51', 'u55', 'u61'].

## 5. Part 2 economics: 50M input + 10M output tokens / month (from the live token mix)

| Configuration | Monthly cost | US$ | Saving vs frontier |
|---|---|---|---|
| Always-cheapest (conversations) | ₹511 | $6 | 95% |
| Always-frontier (GLM-5.3) | ₹10,200 | $116 | 0% |
| Router | ₹2,373 | $27 | 77% |

**Four numbers:** cheapest ₹511, frontier ₹10,200, router ₹2,373; router saves **77%** vs frontier.

| Sensitivity | Cheapest | Frontier | Router | Router saving |
|---|---|---|---|---|
| Headline: fixed 10M output tokens | ₹511 | ₹10,200 | ₹2,373 | 77% |
| Output scales with each config's measured output (incl. reasoning) | ₹282 | ₹10,200 | ₹1,350 | 87% |
| Hard traffic doubled | ₹515 | ₹10,200 | ₹2,719 | 73% |
| Sarvam intro price ends (assumed ₹13.5 / ₹45 per 1M) | ₹803 | ₹10,200 | ₹2,557 | 75% |

Router token mix (share of input / output tokens): glm-5.3 21% / 33%, glm-5.3-flash 1% / 11%, sarvam-105b 48% / 40%, sarvam-105b-conversations 30% / 16%

Prices: Sarvam list prices (₹ per 1M, ex-GST) as of 2026-11-18; US$ at ₹88.0/$.