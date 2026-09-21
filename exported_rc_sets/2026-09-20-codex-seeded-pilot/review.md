# Seeded Codex pilot and lean request audit — 2026-09-20

Incomplete: no completed hard or elite set. Hard passage/questions finished;
the Sol solver then hit the ChatGPT subscription usage limit. Elite never
started. No paid Astra/Sol fallback or reset credit was used. Luna API checks
did run, so the batch's zero-dollar failure summary is not total API spend.

Hard draft blueprint: `BP_260920_b787f706`.
Seed: `04c29f99-1d86-42cc-87e5-b1dc2c244bc4`, Hedgehog Review,
“She Also Found It at the Movies”. The configured legacy policy generated
film restoration from a film-criticism seed; it is seeded inspiration, not
strict source fidelity. Move-signature F1 was 0.83. Drafts are unvalidated,
not client deliverables; solver and subsequent gates are outstanding.

| Stage | Model / effort | Input (includes cached) | Cached subset | Output (includes reasoning) | Reasoning subset |
|---|---|---:|---:|---:|---:|
| Refine | Sol / low | 6,445 | 0 | 1,433 | 634 |
| Render | Astra / low | 17,330 | 8,064 | 1,454 | 112 |
| Questions | Astra / xhigh | 22,493 | 7,296 | 19,693 | 15,132 |

Total 68,848 tokens for these three completed calls. Do not add cached or
reasoning subsets again. The failed solver reported no usage. Earlier failed
refine attempts are separate: initial seedless 7,035 tokens, then seeded
7,723 and 7,993 tokens. No sets shipped from those attempts.

The initial adapter incorrectly rejected a known disabled-code-host startup
notice even when a completed answer followed. The exact notice is now handled;
real errors, tool events and incomplete turns still fail. Seed ancestry lookup
now deduplicates seed IDs before requesting Chroma embeddings.

## Lean configuration correction

The CLI model catalog forced code-mode/agent tool schemas despite disable
flags. A local fake-provider capture proved this; no model call was made.
The adapter now supplies a text-only copy of the installed model catalog,
keeps Astra/Sol identities and reasoning support, and omits optional tools,
skills, collaboration instructions and environment context. Sandbox and
permission enforcement remain. Global user config was not edited.

Synthetic serialized input: **23,026 → 918 characters** (96.0% smaller).
Final captures for both Astra and Sol contain **zero tool schemas**, including
schemas embedded inside input messages. This is a local request-size measure,
not a production token measurement or proof of equal Claude token efficiency.
The stage system/user prompt is unchanged, as is the requested reasoning
ladder. Hard questions used 15,132 reasoning tokens before this correction;
that reasoning cost cannot be attributed solely to harness overhead.

Artifacts retained: `run*.log`, health snapshots, baseline, and raw draft
answers. These drafts must not be treated as approved RC sets. No live run
was restarted during the token audit; quota blocked completing the pilot.
