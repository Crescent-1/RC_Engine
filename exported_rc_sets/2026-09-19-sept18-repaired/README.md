# 18 September batch — repaired delivery candidate

Revised 19 September 2026, Asia/Calcutta. All eight passages retained, with
genre exceptions flagged as instructed. This folder contains the revised TXT
sets; each includes its complete questions, answer key and elimination logic.
Original exports, the database, trackers and existing DOCX remain unchanged.

The revised mix is **five Hard and three Medium**. The original RC IDs and
filenames remain stable for traceability; the **Tier** field inside each file
is authoritative. Original automated scores, compliance figures and screen
verdicts were not carried forward as evaluations of the edited text. These
files are labelled `revised_candidate`.

## Final measurements

Every set has **A2/B2/C2/D2**. All 256 options start with a capital and end with
a full stop. Every question's longest/shortest ratio is below **1.30** by both
characters and words.

Character counts include spaces and punctuation but exclude option labels.
The character longest/shortest counts below include ties, conservatively.
Word counts use whitespace splitting, matching the engine; lexical passage
counts exclude standalone punctuation and retain internal apostrophes/hyphens.
Word-length ties are listed separately in `audit.json`, rather than treated as
unique longest/shortest answers. No set has more than three uniquely longest
or uniquely shortest correct answers by word count either.

| RC suffix | Revised tier | Passage words / lexical | Max character ratio | Max word ratio | Correct longest / shortest, characters |
|---|---|---:|---:|---:|---:|
| 0093 | Hard (was Elite) | 547 / 544 | 1.288 | 1.154 | 2 / 2 |
| 0102 | Hard | 546 / 544 | 1.239 | 1.231 | 2 / 3 |
| 0077 | Hard (was Medium) | 507 / 507 | 1.252 | 1.294 | 3 / 1 |
| 0078 | Medium | 545 / 545 | 1.284 | 1.294 | 2 / 1 |
| 0080 | Medium | 547 / 544 | 1.216 | 1.250 | 2 / 2 |
| 0081 | Hard (was Medium) | 544 / 542 | 1.284 | 1.188 | 2 / 2 |
| 0082 | Medium | 547 / 544 | 1.213 | 1.250 | 2 / 3 |
| 0103 | Hard | 545 / 541 | 1.267 | 1.158 | 0 / 3 |

## Rebuilt answer keys

| RC suffix | Q1 | Q2 | Q3 | Q4 | Q5 | Q6 | Q7 | Q8 |
|---|---|---|---|---|---|---|---|---|
| 0093 | C | D | B | A | B | C | A | D |
| 0102 | C | A | B | D | B | C | D | A |
| 0077 | A | A | C | D | C | D | B | B |
| 0078 | B | A | C | D | D | C | B | A |
| 0080 | C | C | D | B | B | D | A | A |
| 0081 | B | C | D | D | A | C | B | A |
| 0082 | C | A | D | C | B | B | D | A |
| 0103 | A | C | C | D | A | B | D | B |

## Repairs and genre decisions

- **0093:** Cut 570 to 547 words; relabelled Hard; reordered Q2 and Q5;
  shortened the thesis answer while retaining its logic. Art/design history
  fits the brief.
- **0102:** Cut 563 to 546 words; balanced Q1–Q3; corrected option case and
  punctuation in Q2–Q4; reordered Q5. Law/public policy is a retained genre
  exception.
- **0077:** Relabelled Hard. Reordered and edited the argument into a conceptual
  distinction, an evidential objection and analogy, a household illustration,
  and a discussion of methodological costs and burden of proof. This differs
  from 0078's definition/counts, invisible cases, resource consequences and
  comparative verdict. Preserved the household facts, analogy, agency claim,
  administrative consequences and ending's burden. Balanced Q3 and reduced
  the answer-length signal through Q1, Q5 and Q6; corrected Q4/Q8 formatting;
  reordered Q5 and updated affected rationales. Anthropology with an
  epistemological argument remains a borderline genre exception.
- **0078:** Balanced Q5/Q7, capitalized Q7 and reordered Q4/Q5 to introduce D.
  Q4 is now an explicit strengthening question: its existing evidence,
  alternatives and correct-answer logic are preserved, without the prohibited
  “best license” stem. Shortened the thesis answer without changing its claim.
  Social policy/statistics is a retained genre exception.
- **0080:** Balanced Q1/Q4 and reordered Q6. Legislative/administrative history
  is a retained genre exception.
- **0081:** Relabelled Hard; balanced Q2; replaced Q5 with the rhetorical function
  of the tailor-and-coat comparison, rather than another statement of the
  thesis. It also avoids duplicating Q6's colonial-instruction exception.
  Corrected Q8 formatting and reordered it to A. Political philosophy and
  intellectual history are defensible within the brief.
- **0082:** Cut 565 to 547 words; balanced Q4; adjusted Q2's correct-answer
  length; reordered Q3/Q7 and capitalized Q7/Q8. Urban/cultural governance is
  a retained genre exception.
- **0103:** Cut 581 to 545 words; balanced Q2 and corrected Q2/Q4 case.
  Completely replaced Q8 with an application/inference requiring the reader
  to combine the pooled-fund proposal with the earlier knowledge-dependence
  analysis. Q6 and Q8 now supply B answers. Applied philosophy/institutional
  ethics fits the brief; Hard remains defensible.

All 62 unreplaced questions retain their original intended answer logic.
Relettered options carry their corresponding rationales; rationales affected
by trimming, structural edits or rewording were updated.

## Replacement-question re-solve

The final passage and replacement question were reread with the key and
elimination block withheld. This is a **same-editor key-hidden re-solve**, not
an independent cold solve by another model or reviewer.

- **0081 Q5 → A.** Refitting the coat permits adaptation while its original cut
  remains visible. B denies the possibility of adaptation; C substitutes
  restoration for adaptation; D assigns an existing mismatch to later readers.
  The item asks what a particular comparison accomplishes, unlike Q1's gist.
- **0103 Q8 → B.** Independent allocation removes appointment control, whereas
  usable technical understanding can still reside with the manufacturer.
  A confuses reporting with technical sufficiency; C confuses knowledge
  dependence with selection power; D reverses the argument about rotation.
  The item draws together two mechanisms, rather than asking for an assumption
  that licenses the old inference.

## Verification and scope

- Rebuilt and reparsed all eight files: 64 questions, 256 options, 64 correct
  labels and 256 option rationales; exactly one CORRECT rationale per question.
- Checked both passage-count methods, both option-ratio methods, answer-length
  positions, case, punctuation, key distribution and prohibited stem wording.
- Reviewed the evidence used by questions and rationales after passage edits.
  Checked previously verbatim passage quotations in both single and double
  quotes for missing spans; no dangling original quotation remains.
- A separate read-only validation pass confirmed the measurements, UTF-8/LF
  formatting and original/revised SHA-256 hashes. Original exports are intact.
- The rebuild script parsed successfully; `git diff --check` passed. Engine
  tests were not run because no production engine code changed.
- No paid generation, independent solver, fresh automated quality/novelty
  evaluation or external factual audit was run. Historical source attributions
  remain as supplied. The genre exceptions make this unsuitable for a strict
  philosophy/literature/art-only brief without further replacement work.

`audit.json` contains per-question lengths, ratios, positions, source hashes
and original-to-revised letter maps for unreplaced questions.
`tools/repair_20260918.py` at the project root reproduces the TXT files and
machine audit from the original exports. Changes are uncommitted.
