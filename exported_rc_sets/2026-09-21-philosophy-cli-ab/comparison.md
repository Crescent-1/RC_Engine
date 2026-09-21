# Philosophy hard: Claude CLI vs OpenAI CLI

## Matched controls

- Seed ID: `b208e303-6a7c-4d26-9f4f-716742e027ab`
- Seed title: “Are Doctors Heroes?”
- Source: <https://www.thenewatlantis.com/practicing-medicine/are-doctors-heroes>
- Seed labels: philosophy / conceptual essay; source kind `idea_essay`
- Tier and policy: hard / `cat-pyq-f4`
- Deterministic RNG seed: `20260921`
- Effort: `low` in both CLI lanes
- Structural components: `F04/P15/E13/T19/R02/D12/QT10`, instability `0.42`
- Inputs: independent database copies made from one production snapshot before
  either run
- Checks: the same Luna seed-fidelity, move-signature, compliance,
  answerability/judging, and similarity-screening pipeline

The Claude lane used Sonnet for refine/solver and Opus for render/questions.
The OpenAI lane used Sol for refine/solver and Astra for render/questions.

## Measurements

| Measure | Claude CLI | OpenAI CLI |
|---|---:|---:|
| Internal RC ID | `RC-HARD-260920-0106` | `RC-HARD-260920-0106` |
| Passage words | 528 | 526 |
| Final status | `solver_dispute` | `needs_review` |
| Judge score | unavailable after dispute | 8.8 |
| Compliance F1 | 0.777 | 0.839 |
| Novelty composite | 0.629 | 0.594 |
| Similarity screen | indeterminate against `RC-ELITE-260920-0094` | red against `RC-ELITE-260914-0089` |
| CLI calls | 4 | 4 |
| CLI input + cache-write tokens | 37,227 | 14,883 |
| CLI output tokens | 6,688 | 5,564 |
| Thinking tokens (subset of output) | 178 | 578 |
| Complete reported CLI tokens | **43,915** | **20,447** |
| CLI notional API list price | $0.3305 | $0.3329 |
| Luna generation/check spend | $0.0070 | $0.0073 |
| Similarity-screen spend | $0.0020 | $0.0023 |
| Total real API spend | $0.0090 | $0.0096 |

OpenAI reported 23,468 fewer tokens, or 53.4% fewer than Claude's complete
all-model total, in this single controlled run. Provider tokenizers and usage
envelopes are not perfectly interchangeable, so the result is directional
rather than a general benchmark.

Claude's original summary displayed 30,119 tokens because its top-level
`usage` object omitted an internal Haiku helper used on all four calls. Its raw
`modelUsage` records contain another 13,796 helper tokens, producing the
43,915-token all-model total above. The accounting code now prefers the
complete `modelUsage` ledger without double-counting the primary model.

## Quality disposition

Neither result is approved for the production corpus. Claude's solver disputed
Q6; the independent Luna tiebreak supported the authored key, but the set
remains `solver_dispute`. OpenAI cleared its judge with 8.8 but its similarity
screen found a red structural match. The two text exports are retained for
human comparison only, and the shared source seed was deliberately not marked
used.

Both exports contain eight question stems, eight answer-key entries, and no
Unicode replacement characters.
