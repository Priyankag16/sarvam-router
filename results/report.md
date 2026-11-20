# Results (MOCK run, 40 held-out prompts)

> **MOCK RUN.** Latency, quality and failures are simulated from the stated assumptions in `router/call.py`. Token counts are estimates; prices are real Sarvam list prices. Rerun with an API key before quoting these as measurements.

## 1. Baselines vs router

| Metric | Always-cheapest (105B) | Always-frontier (GLM-5.3) | Router |
|---|---|---|---|
| Total cost, 40 requests (₹) | 0.3064 | 10.1031 | 1.8435 |
| Cost per request (₹) | 0.00766 | 0.25258 | 0.04609 |
| p50 latency (ms) | 4320 | 13200 | 4210 |
| p95 latency (ms) | 7826 | 18312 | 18312 |
| p95 latency, live voice only (ms) | 5776 | 16399 | 2594 |
| Mean quality (1-5) | 3.88 | 4.10 | 4.39 |
| Mean quality excl. fault-injected prompts | 4.03 | 4.26 | 4.39 |
| Quality: hard slice | 3.38 | 4.05 | 4.04 |
| Quality: hardest 10% (4 prompts) | 3.81 | 4.55 | 4.45 |
| Quality: English | 3.44 | 4.08 | 4.29 |
| Quality: Hindi/Punjabi/Hinglish | 4.09 | 4.04 | 4.37 |
| Fallback fired (% of requests) | 2% | 2% | 8% |
| Gave up (count) | 4 | 3 | 0 |

Router vs always-frontier: **82% cheaper** (95% bootstrap CI 69% to 93%); quality difference +0.28 (CI -0.01 to +0.64).
Router overhead (classification) per request: mean 0.321 ms, 0 tokens, ₹0.

## 2. Per segment

| Segment | Config | Cost (₹) | p95 (ms) | Quality |
|---|---|---|---|---|
| bfsi | always_cheapest | 0.1099 | 24952 | 3.93 |
| bfsi | always_frontier | 3.5907 | 42214 | 4.47 |
| bfsi | router | 0.7651 | 24953 | 4.47 |
| telecom | always_cheapest | 0.0995 | 6987 | 3.83 |
| telecom | always_frontier | 3.4262 | 18250 | 4.17 |
| telecom | router | 0.4121 | 18250 | 4.39 |
| agri_gov | always_cheapest | 0.0971 | 7613 | 3.88 |
| agri_gov | always_frontier | 3.0861 | 16446 | 3.61 |
| agri_gov | router | 0.6664 | 16328 | 4.29 |

## 3. Where the router sent traffic

| Rule | Requests | Final model(s) |
|---|---|---|
| R1-attack | 2 | none (template) ×2 |
| R1-junk | 2 | none (template) ×2 |
| R2-voice-easy | 5 | sarvam-105b-conversations ×5 |
| R2-voice-hard | 1 | sarvam-105b ×1 |
| R3-hard-en | 5 | glm-5.3 ×5 |
| R3-hard-indic | 7 | sarvam-105b ×7 |
| R4-simple | 10 | sarvam-105b ×8, glm-5.3-flash ×2 |
| R5-default | 8 | sarvam-105b ×8 |

Hard prompts routed as not-hard (under-routing): ['b09']. Non-hard prompts routed as hard (over-routing): ['b04', 't12', 'a07'].
Human review flagged: 7 requests (b04:review_queue, b05:review_queue, b09:warm_handoff, b10:review_queue, t09:review_queue, a04:review_queue, a05:review_queue).

## 4. Part 2 economics: 50M input + 10M output tokens / month

| Configuration | Monthly cost (₹) | (US$) | Saving vs frontier |
|---|---|---|---|
| always_cheapest | ₹775 | $9 | 93% |
| always_frontier | ₹10,509 | $119 | 0% |
| router | ₹2,649 | $30 | 75% |

**Four numbers:** cheapest ₹775, frontier ₹10,509, router ₹2,649; router saves **75%** vs frontier.

| Sensitivity | Cheapest | Frontier | Router | Router saving |
|---|---|---|---|---|
| Headline (fixed 10M output) | ₹775 | ₹10,509 | ₹2,649 | 75% |
| Output scales with measured reasoning tokens | ₹632 | ₹10,509 | ₹2,006 | 81% |
| Hard traffic doubled | ₹769 | ₹10,441 | ₹3,144 | 70% |
| Sarvam-105B intro price ends (assumed ₹13.5/₹45) | ₹1,158 | ₹10,509 | ₹2,935 | 72% |

Router token mix (share of input / output tokens): glm-5.3 13% / 30%, glm-5.3-flash 5% / 1%, sarvam-105b 73% / 67%, sarvam-105b-conversations 9% / 3%

Prices: Sarvam list prices (₹/1M, ex-GST) as of 2026-11-18; US$ at ₹88.0/$.