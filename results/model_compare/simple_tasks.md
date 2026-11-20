# Simple tasks: model comparison (11 prompts, live API)

| Model | Score (of 11) | Exact-right | Cost ₹ (11 req) | Avg reasoning tokens | p50 latency | p95 latency | Timeouts/errors |
|---|---|---|---|---|---|---|---|
| glm-5.3 (default) | **11** | 11/11 | 0.8071 | 160 | 1.7 s | 2.3 s | 0 |
| glm-5.3-flash (default) | **9** | 7/11 | 0.0206 | 14 | 0.7 s | 1.6 s | 0 |
| sarvam-105b (default) | **11** | 11/11 | 0.1455 | 496 | 3.1 s | 4.3 s | 0 |
| sarvam-105b-conversations | **10.5** | 10/11 | 0.0092 | 0 | 0.2 s | 0.5 s | 0 |
| sarvam-105b LOW (router run) | **10** | 10/11 | 0.1421 | 484 | 2.7 s | 21.1 s | 1 |

## Per prompt (score, note, answer)

**u01** (classification, en) expected `complaint`
- glm-5.3 (default): **1**  → `complaint`
- glm-5.3-flash (default): **1**  → `complaint`
- sarvam-105b (default): **1**  → `complaint`
- sarvam-105b-conversations: **1**  → `complaint`
- sarvam-105b LOW (router run): **1**  → `complaint`

**u02** (classification, hi) expected `complaint`
- glm-5.3 (default): **1**  → `complaint`
- glm-5.3-flash (default): **1**  → `complaint`
- sarvam-105b (default): **1**  → `complaint`
- sarvam-105b-conversations: **1**  → `complaint`
- sarvam-105b LOW (router run): **0** wrong: 'शिकायत' → `शिकायत`

**u03** (classification, rom_pa) expected `balance_query`
- glm-5.3 (default): **1**  → `balance_query`
- glm-5.3-flash (default): **1**  → `balance_query`
- sarvam-105b (default): **1**  → `balance_query`
- sarvam-105b-conversations: **1**  → `balance_query`
- sarvam-105b LOW (router run): **1**  → `balance_query`

**u04** (extraction, en) expected `{"amount": 2300, "date": "14 Oct"}`
- glm-5.3 (default): **1**  → `{"amount": 2300, "date": "14 Oct"}`
- glm-5.3-flash (default): **0.5** amount '2,300' → `{"amount": "2,300", "date": "14 Oct"}`
- sarvam-105b (default): **1**  → `{"amount":2300,"date":"14 Oct"}`
- sarvam-105b-conversations: **1**  → `{ ⏎   "amount": 2300, ⏎   "date": "14 Oct" ⏎ }`
- sarvam-105b LOW (router run): **1**  → `{"amount":2300,"date":"14 Oct"}`

**u05** (extraction, hi) expected `{"amount": 18750, "date": "5 Nov"}`
- glm-5.3 (default): **1**  → `{"amount": 18750, "date": "5 Nov"}`
- glm-5.3-flash (default): **0.5** amount '18,750' → `{"amount": "18,750", "date": "5 Nov"}`
- sarvam-105b (default): **1**  → `{ ⏎   "amount": 18750, ⏎   "date": "5 Nov" ⏎ }`
- sarvam-105b-conversations: **1**  → `{ ⏎   "amount": 18750, ⏎   "date": "5 Nov" ⏎ }`
- sarvam-105b LOW (router run): **1**  → `{"amount":18750,"date":"5 Nov"}`

**u06** (extraction, pa) expected `{"amount": 6000, "date": "22 Sep"}`
- glm-5.3 (default): **1**  → `{"amount": 6000, "date": "22 Sep"}`
- glm-5.3-flash (default): **0.5** amount '6000' → ````json ⏎ {"amount": "6000", "date": "22 Sep"} ⏎ ````
- sarvam-105b (default): **1**  → `{"amount": 6000, "date": "22 Sep"}`
- sarvam-105b-conversations: **0.5** amount '6000' → `{ ⏎   "amount": "6000", ⏎   "date": "22 Sep" ⏎ }`
- sarvam-105b LOW (router run): **1**  → `{"amount": 6000, "date": "22 Sep"}`

**u07** (extraction, en) expected `{"amount": 4000, "date": "2 Nov"}`
- glm-5.3 (default): **1**  → `{"amount": 4000, "date": "2 Nov"}`
- glm-5.3-flash (default): **0.5** amount '4000' → `{"amount": "4000", "date": "2 Nov"}`
- sarvam-105b (default): **1**  → `{"amount": 4000, "date": "2 Nov"}`
- sarvam-105b-conversations: **1**  → `{"amount":4000,"date":"2 Nov"}`
- sarvam-105b LOW (router run): **1**  → `{"amount":4000,"date":"2 Nov"}`

**u11** (classification, hinglish) expected `card_block`
- glm-5.3 (default): **1**  → `card_block`
- glm-5.3-flash (default): **1**  → `card_block`
- sarvam-105b (default): **1**  → `card_block`
- sarvam-105b-conversations: **1**  → `card_block`
- sarvam-105b LOW (router run): **1**  → `card_block`

**u12** (classification, rom_pa) expected `loan_info`
- glm-5.3 (default): **1**  → `loan_info`
- glm-5.3-flash (default): **1**  → `loan_info`
- sarvam-105b (default): **1**  → `loan_info`
- sarvam-105b-conversations: **1**  → `loan_info`
- sarvam-105b LOW (router run): **1**  → `loan_info`

**u24** (classification, en) expected `positive`
- glm-5.3 (default): **1**  → `Positive`
- glm-5.3-flash (default): **1**  → `Positive`
- sarvam-105b (default): **1**  → `positive`
- sarvam-105b-conversations: **1**  → `positive`
- sarvam-105b LOW (router run): **1**  → `positive`

**u25** (classification, en) expected `negative`
- glm-5.3 (default): **1**  → `Negative`
- glm-5.3-flash (default): **1**  → `negative`
- sarvam-105b (default): **1**  → `Negative`
- sarvam-105b-conversations: **1**  → `negative`
- sarvam-105b LOW (router run): **1**  → `Negative`
