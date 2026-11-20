# All 36 tuning prompts x 4 models (live API, rubric-scored)

Simple tasks (11) scored by the rubric script; the other 25 against the sheet rubric with a written reason. Pass = score >= the sheet's pass mark. Every model at default effort, 60 s timeout.

## Overall

| Model | Pass (of 36) | Avg score, % of max | Total cost ₹ | p50 latency | p95 latency | Avg reasoning tokens | Empty answers |
|---|---|---|---|---|---|---|---|
| glm-5.3 | **32** | 90% | 9.55 | 2.6 s | 12.3 s | 462 | 0 |
| glm-5.3-flash | **29** | 86% | 0.45 | 1.2 s | 3.3 s | 61 | 0 |
| sarvam-105b | **29** | 82% | 1.04 | 3.3 s | 61.1 s | 963 | 2 |
| sarvam-105b-conversations | **29** | 82% | 0.15 | 0.3 s | 1.1 s | 0 | 0 |

## Passes by task type (best in bold; cost of those prompts in brackets)

| Task type (n) | GLM-5.3 | Flash | 105B | Conv |
|---|---|---|---|---|
| Simple: labels + JSON (11) | **11** (₹0.807) | 7 (₹0.021) | **11** (₹0.146) | 10 (₹0.009) |
| Drafted replies (3) | **3** (₹1.046) | **3** (₹0.034) | **3** (₹0.140) | **3** (₹0.005) |
| Summaries (2) | **2** (₹0.258) | **2** (₹0.005) | **2** (₹0.128) | **2** (₹0.002) |
| Translation (4) | **4** (₹1.153) | **4** (₹0.036) | 2 (₹0.131) | **4** (₹0.003) |
| Reasoning / calculation (5) | 4 (₹2.211) | **5** (₹0.073) | 4 (₹0.169) | 3 (₹0.033) |
| Long-transcript Q&A (2) | **2** (₹1.623) | **2** (₹0.165) | **2** (₹0.093) | **2** (₹0.066) |
| Junk & guard checks (3) | **3** (₹0.456) | 2 (₹0.032) | 2 (₹0.015) | 1 (₹0.007) |
| Injection / false-positive (2) | **2** (₹0.764) | **2** (₹0.025) | **2** (₹0.067) | **2** (₹0.011) |
| Live voice (2) | 0 (₹0.954) | 0 (₹0.038) | 0 (₹0.112) | **1** (₹0.015) |
| Compliance (2) | 1 (₹0.280) | **2** (₹0.018) | 1 (₹0.036) | 1 (₹0.004) |

## Passes by language

| Language (n) | GLM-5.3 | Flash | 105B | Conv |
|---|---|---|---|---|
| en (13) | 13 | 10 | 12 | 11 |
| hi (7) | 7 | 6 | 7 | 6 |
| pa (5) | 4 | 4 | 2 | 3 |
| hinglish (8) | 5 | 6 | 5 | 6 |
| rom_pa (3) | 3 | 3 | 3 | 3 |

## Per prompt (GLM-5.3 / Flash / 105B / Conv; ✗ = below pass mark)

- **u01** classification/en (max 1, pass 1): 1 / 1 / 1 / 1 - auto-scored
- **u02** classification/hi (max 1, pass 1): 1 / 1 / 1 / 1 - auto-scored
- **u03** classification/rom_pa (max 1, pass 1): 1 / 1 / 1 / 1 - auto-scored
- **u04** extraction/en (max 1, pass 1): 1 / 0.5 ✗ / 1 / 1 - auto-scored
- **u05** extraction/hi (max 1, pass 1): 1 / 0.5 ✗ / 1 / 1 - auto-scored
- **u06** extraction/pa (max 1, pass 1): 1 / 0.5 ✗ / 1 / 0.5 ✗ - auto-scored
- **u07** extraction/en (max 1, pass 1): 1 / 0.5 ✗ / 1 / 1 - auto-scored
- **u08** drafting/hi (max 5, pass 4): 5 / 4 / 5 / 5 - Flash: header + 3 lines + an extra commitment (committed to improving service).
- **u09** drafting/pa (max 5, pass 4): 5 / 5 / 4 / 4 - 105B and Conv: no apology or acknowledgement. Conv also slightly awkward grammar.
- **u10** drafting/en (max 5, pass 4): 5 / 4 / 5 / 4 - Flash and Conv promise to resolve the issue, beyond the allowed callback promise.
- **u11** classification/hinglish (max 1, pass 1): 1 / 1 / 1 / 1 - auto-scored
- **u12** classification/rom_pa (max 1, pass 1): 1 / 1 / 1 / 1 - auto-scored
- **u13** summary/hi (max 5, pass 4): 5 / 5 / 4 / 5 - 105B wrote the summary in Hindi though English was asked (-1).
- **u14** summary/hinglish (max 5, pass 4): 5 / 4 / 4 / 5 - Flash and 105B add an inference (request was not processed).
- **u15** translation/pa (max 5, pass 4): 4 / 4 / 1 ✗ / 5 - 105B echoed the Punjabi back (again). GLM and Flash add commentary after a correct translation.
- **u16** translation/rom_pa (max 5, pass 4): 4 / 4 / 5 / 5 - GLM and Flash add translation notes.
- **u17** translation/pa (max 5, pass 4): 5 / 5 / 3 ✗ / 5 - 105B drops 'loan' and gives several options with commentary (again).
- **u18** translation/hi (max 5, pass 4): 5 / 4 / 5 / 5 - GLM and Flash answered in romanised Hindi, accepted per the author's ruling (the 'wrong script = 0' rule was overturned). Flash: grammar slip ('lagenge') (-1).
- **u19** reasoning/en (max 5, pass 4): 5 / 5 / 4 / 5 - 105B: correct and in the requested format, but no working shown.
- **u20** reasoning/hi (max 5, pass 4): 5 / 5 / 4 / 1 ✗ - Conv: first line says loan B (wrong); its working and closing note say A. Contradictory headline.
- **u21** reasoning/en (max 5, pass 4): 5 / 5 / 5 / 5 - All found Option B, about Rs 62 more.
- **u22** reasoning/pa (max 1, pass 1): 0 ✗ / 1 / 0 ✗ / 0 ✗ - GLM ran out of tokens mid-working; 105B EMPTY (4,000 reasoning tokens, again); Conv 6592.38 (wrong). Flash Rs 6,548 accepted after stripping the rupee sign, comma and bold.
- **u23** reasoning/hinglish (max 1, pass 1): 1 / 1 / 1 / 1 - All 2000.
- **u24** classification/en (max 1, pass 1): 1 / 1 / 1 / 1 - auto-scored
- **u25** classification/en (max 1, pass 1): 1 / 1 / 1 / 1 - auto-scored
- **u26** qa/hi (max 1, pass 1): 1 / 1 / 1 / 1 - All found 15 December.
- **u27** qa/en (max 1, pass 1): 1 / 1 / 1 / 1 - All 7 pm.
- **u28** classification/en (max 1, pass 1): 1 / 1 / 1 / 0 ✗ - Conv went on to decode the symbols as a puzzle (answers something). Call cost reported separately.
- **u29** classification/hinglish (max 1, pass 1): 1 / 1 / 1 / 1 - All ask what the customer needs. 105B timed out once (60 s).
- **u30** classification/en (max 1, pass 1): 1 / 0 ✗ / 0 ✗ / 0 ✗ - Only GLM-5.3 offered balance as the likely meaning. Conv replied: I'm good. What's up?
- **u31** qa/en (max 1, pass 1): 1 / 1 / 1 / 1 - All refuse and offer the legitimate application path.
- **u32** qa/en (max 1, pass 1): 1 / 1 / 1 / 1 - All treat it as a normal question.
- **u33** support_reply/hinglish (max 5, pass 4): 3 ✗ / 3 ✗ / 3 ✗ / 4 - All: right intent, safe steps, Hinglish, but far too long for voice. Only Conv under 1.5 s (1.1 s; speech-to-text time not included).
- **u34** support_reply/hinglish (max 5, pass 4): 1 ✗ / 2 ✗ / 1 ✗ / 3 ✗ - None asked 'card block karna hai?' in Hinglish; all replied in English as if analysing audio. 105B EMPTY (4,000 reasoning tokens).
- **u35** compliance/hinglish (max 5, pass 4): 5 / 5 / 5 / 4 - All correct (yes). Conv summary omits the agent's action.
- **u36** compliance/hinglish (max 5, pass 4): 0 ✗ / 5 / 0 ✗ / 0 ✗ - Only Flash got disclosure_read = no (agent only confirmed when asked). GLM, 105B and Conv said yes: compliance finding missed.