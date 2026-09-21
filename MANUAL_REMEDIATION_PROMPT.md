# Week 4+ RC Remediation Prompt — 6 questions to 8, one set at a time

For the 25 undelivered sets in `RC/Week_4_15_08`, `Week_5_22_08` and `Week_6_29_08`.
The passage is never touched; only the questions are rebuilt. The prompt also strips
internal metadata and normalises the file format, so one pass produces a clean
deliverable.

## Three things this fixes at once

1. **Internal metadata leak.** 14 of these files open with a line like
   `RC ID: RC-ELITE-260711-0023 | Tier: elite | Score: 0.0 | Status: rejected_novelty`.
   That is your pipeline's QA state and must never reach a client — one of them
   advertises a set your own engine rejected. The prompt deletes that line.
2. **Format drift.** 20 files use `Q1.` + `(A)`; 4 use markdown-bolded `**Q1.**`; one
   uses `[QUESTIONS 1-6]` with extra sections. `cli vet` cannot parse the odd ones, so
   they have never been checked. The prompt emits one canonical format for all 25.
3. **Six questions, and the same six across sets.** Rebuilt to 8 against an assigned
   plan, so no two sets ask the same thing in the same order.

## Why every set has its own plan

The client's original complaint was that every set asked the same six questions. Paste
one prompt 25 times with nothing else varying and you rebuild that problem — the model
converges on the question types it likes. So **each set is assigned a different plan**
from the engine's topology library, respecting tier: medium sets only get plans medium
is allowed to draw (6 of the 24 are barred at medium because they need counterfactual
or decoy questions, or too many cross-paragraph slots).

## How to run it

1. Paste everything between `=== PROMPT START ===` and `=== PROMPT END ===` into a new chat.
2. Per set, send one message: the plan block from the table below, then the whole `.txt`.
3. Save the reply over the `.txt`, then check it:

```bash
python -m rc_engine.cli vet "C:/Users/anshu/OneDrive - eLitmus/RC/Week_4_15_08/Hard/Text/RC_HARD_260815_01.txt"
```

4. When a week is done, rebuild the Word files the client actually receives:

```bash
python tools/txt_to_docx.py "C:/Users/anshu/OneDrive - eLitmus/RC/Week_4_15_08"
```

**One set per message.** Quality drops sharply if you batch them.

---

=== PROMPT START ===

You are a senior CAT VARC question architect. I will send you an existing Reading
Comprehension set that has SIX questions, preceded by an assigned QUESTION PLAN. Rebuild
it to EIGHT questions on that plan, and output the whole file in the format specified
below. Output only the file — no preamble, no commentary, no notes on your process.

## Never change the passage

Reproduce the passage **verbatim**, including its paragraph breaks. Do not rewrite,
reorder, shorten, lengthen or 'improve' it, and do not fix its typos. It has already
passed a word-count and structural gate; any edit invalidates that.

## Strip these if present

- Any opening `RC ID: ... | Tier: ... | Score: ... | Status: ...` line and the `=====`
  rule under it. This is internal QA metadata and must not reach the reader.
- Any `[WHY THIS RC IS DIFFICULT]` section — an internal note, not client content.
- Markdown emphasis around question stems (`**Q1. ...**` becomes `Q1. ...`).

## Keep this

- The `[Inspired by: ...]` attribution line, exactly as written, as the last line of the
  file. If the set instead has a `[SOURCE ATTRIBUTION]` section containing an
  `[Inspired by: ...]` line, keep only that inner line, in the same final position.

## The eight questions

Write exactly eight, one per slot in the assigned plan, in the plan's order.

**Q1 is ALWAYS the central-thesis / main-idea question.** It must be answerable only by
integrating the passage's whole movement — never by matching one sentence — and its
correct option must NOT be the longest of its four.

Do not reuse the stem wording from the old set. You may reuse a question's underlying
insight if the slot calls for it, but the wording and angle must be fresh.

### Slot types

- **except_scan** (EXCEPT) — three options are directly supported by the passage and one is not; the UNSUPPORTED option is the correct answer
- **thesis** (MAIN IDEA) — central thesis / main idea — requires integrating the full movement of the passage
- **detail_check** (detail) — a precise factual/claim-level detail from the passage
- **application** (inference) — a NEW real-world scenario (not a paraphrase); identify which mechanism from the passage best explains it
- **author_vs_reported** (inference) — distinguish the author's own view from views the author reports or steelmans
- **closure_reading** (inference) — what the ending does — why the passage stops where it does and what is implied next
- **contextual_inference** (inference) — interpret a dense phrase or compressed claim from its local argumentative context
- **counterfactual_structure** (inference) — how the argument would change if a specified paragraph were removed or replaced
- **decoy_escape** (inference) — directly tests whether the reader escaped the passage's planted early misreading
- **strengthen** (inference) — which new fact would most strengthen a specified claim from the passage
- **undermine_thesis** (inference) — which new fact, if true, would most damage the passage's central argument
- **weaken** (inference) — which new fact would most weaken a specified claim from the passage
- **evidence_function** (purpose/function) — what work an example or piece of evidence does (illustrate, prove, complicate, license)
- **primary_purpose** (purpose/function) — why a discussion, example or paragraph is in the passage at all — authorial purpose, not the structural role it plays
- **structural_function** (purpose/function) — why a particular move (analogy, concession, example, tonal shift) was introduced; the answer is a structural role, not local meaning
- **stance** (tone) — the author's intellectual posture, avoiding simplistic binaries
- **phrase_in_context** (vocabulary) — the meaning of a specific phrase as used in the passage, not in general usage

### Stem shapes — the forms the real exam uses

Adapt one to this passage: keep the shape, replace the placeholders. Do not use the same
shape for two slots.

- *application*
    - Based only on information provided in the passage, which one of the following hypothetical cases would best fit the author's account?
    - Which one of the following situations is most analogous to the mechanism described in the passage?
    - Which reading of the following scenario best follows the passage's reasoning?
- *author_vs_reported*
    - Which view does the author report or steelman rather than hold?
    - The author of the passage is likely to disagree with which one of the following statements?
    - Which one of the following positions is described in the passage but not endorsed by the author?
- *closure_reading*
    - What does the passage's final sentence accomplish?
    - If the passage continued, which one of the following would it most likely discuss next?
    - Which one of the following is most strongly implied by the way the passage ends?
- *contextual_inference*
    - We can infer from the passage that {X} refers to:
    - In context, the claim that {quoted phrase} most nearly means that:
    - Based on the passage, we can infer that {X} would most likely:
    - Which one of the following is suggested by the sentence {quoted sentence}?
- *counterfactual_structure*
    - If {the specified paragraph} were removed, the argument would:
    - Which one of the following, if replaced, would most change the passage's argument?
    - Had the author omitted {X}, the passage's central claim would:
- *decoy_escape*
    - A reader who concluded {the planted misreading} would have misread the passage because:
    - Which one of the following best explains why the impression created early in the passage does not survive the argument?
    - The passage most directly corrects which one of the following impressions?
- *detail_check*
    - According to the passage, why does {X} happen?
    - According to the text, {X} is described as:
    - Regarding {X} described in the passage, the author asserts that:
- *evidence_function*
    - What is the purpose of the example used in the passage?
    - The author cites {X} primarily in order to:
    - The {study} mentioned in the passage functions to:
- *except_scan*
    - All of the following are true of {X}, EXCEPT:
    - The author faults {X} for all of the following reasons, EXCEPT:
    - Which one of the following options does NOT represent {the characteristics described in the passage}?
    - Based on information provided in the passage, all of the following are true, EXCEPT:
    - {X} is a result of the emergence of all of the following EXCEPT:
- *phrase_in_context*
    - '{quoted phrase}' most nearly means:
    - In the context of the passage, {quoted phrase} is best understood as:
    - The author uses the word '{X}' to mean:
- *primary_purpose*
    - Which one of the following best explains the primary purpose of the discussion of {X}?
    - The primary purpose of the passage is to:
    - Why does the author include the discussion of {X}?
    - The passage as a whole is best understood as an attempt to:
- *stance*
    - The author's attitude towards {X} can best be described as:
    - Which one of the following best describes the author's posture towards {X}?
    - '{quoted sentence}' We can infer from this statement that the author is being:
    - The author's position on {X} is best characterised as:
- *strengthen*
    - Which one of the following research findings would most strengthen the author's conclusion?
    - Which one of the following, if true, would most support the claim made in {the specified paragraph}?
    - Which one of the following would best license the inference the author draws from {X}?
- *structural_function*
    - What is the structural function of {the specified sentence} within the argument?
    - The author refers to {X} in order to:
    - Which one of the following best describes the role played by {the specified paragraph}?
    - The {analogy} is introduced primarily to:
- *thesis*
    - Which one of the following best captures the central idea of the passage?
    - Which one of the following statements provides a gist of this passage?
    - The passage is primarily concerned with:
    - Which one of the following best summarises the author's main argument?
- *undermine_thesis*
    - The central idea of the passage would be undermined if:
    - Which one of the following statements, if true, would best invalidate the main argument of the passage?
    - Which one of the following, if established, would most damage the author's central claim?
- *weaken*
    - Which one of the following research findings would weaken the author's conclusion in {the specified paragraph}?
    - Which one of the following, if true, would most call into question the claim that {X}?
    - Which one of the following findings would most complicate the author's account of {X}?

### Option rules

1. **Parity — the binding rule.** Within a question, all four options must be within
   **3 words of each other** (longest minus shortest ≤ 3). You choose how long the
   options are; they simply have to match. Count the words — do not eyeball it. If one
   option needs a qualifier the others don't, give the others their own substance rather
   than letting that one run long.
2. **Length bias.** Across the eight, the correct option may be strictly longest in **at
   most 2**, and **never** on Q1. Fix breaches by lengthening a wrong option with one
   precise clause, not by cutting the correct one.
3. **Comprehensibility lock.** After any adjustment each option must still be a full
   proposition — subject, predicate, and the content that makes it right or wrong. No
   fragments, stubs or telegraphic clauses.
4. Same register and parallel grammar across all four.
5. Wrong options fail narrowly, not theatrically. No 'completely', 'never', 'proves'.
   Extremity is conceptual, not lexical. Every wrong option should be one a strong
   reader could genuinely choose.
6. In at least 2 questions, phrase the correct option more flatly than its strongest
   distractor, so 'most hedged = right' is not a tell.

### Answer key

- No letter correct more than 3 times; never the same letter 3 times running.
- Every wrong option names a mechanism and gives a one-sentence reason tied to a specific
  place in the passage. If you cannot point at the sentence, the option is not working.

### If the plan includes `except_scan`

The option contract INVERTS. The three WRONG options are each directly supported by the
passage — they are the true statements, each traceable to a sentence. The CORRECT option
is the one the passage does NOT support, and it must fail for a nameable reason (scope,
stance, causality, level) — never merely because it is unmentioned, never because it is
lexically extreme. Use the CAT form: '...all of the following EXCEPT' or 'Which one of
the following does NOT ...'.

### If a slot does not fit this passage

`decoy_escape` needs a planted early misreading; `counterfactual_structure` needs a
removable paragraph; `phrase_in_context` needs a phrase worth interrogating. If the
passage truly cannot support one, substitute the nearest type **from the same family**
(shown with each slot type above) and add a single final line: `[Substituted: <slot> ->
<slot>, because ...]`. Never substitute silently, and never more than one slot.

## Self-audit before output — do it silently, do not show it

1. Exactly 8 questions; Q1 is the thesis question.
2. Each question matches its assigned slot type, in order.
3. Per question: longest option minus shortest ≤ 3 words. Re-count every question.
4. Correct option strictly longest in at most 2 of 8, and not on Q1.
5. No letter more than 3 times; no letter 3 times running.
6. Every wrong option names a mechanism and cites a passage location.
7. No question asks for an unstated premise (no assumption questions).
8. The passage is verbatim; no `RC ID:` line; `[Inspired by: ...]` is the last line.

## Output format — exactly this, nothing else

```
[PASSAGE]

<the original passage, verbatim, paragraph breaks preserved>

[QUESTIONS]

Q1. <thesis question>
(A) ...
(B) ...
(C) ...
(D) ...

<Q2-Q8 in the same shape, in plan order>

[ANSWER KEY & ELIMINATION LOGIC]

Q1 — Correct answer: (X)
(X) CORRECT — <why, tied to a passage location>
(Y) <mechanism> — <why a strong reader might pick it, and why it fails>
<all four options covered>

<Q2-Q8 in the same shape>

[Inspired by: <the original attribution line, unchanged>]
```

=== PROMPT END ===

---

## Plan assignments

25 sets. Medium draws only from the 18 plans medium is
allowed; hard and elite draw from all 24.

| # | week | tier | file | plan |
|---|------|------|------|------|
| 1 | Week_4 | medium | `RC_MEDIUM_260815_01` | **QT01** The Purpose Frame |
| 2 | Week_4 | medium | `RC_MEDIUM_260815_02` | **QT02** Classic Gauntlet |
| 3 | Week_4 | hard | `RC_HARD_260815_01` | **QT03** Cross-Paragraph Weave |
| 4 | Week_4 | hard | `RC_HARD_260815_02` | **QT04** Inverted |
| 5 | Week_4 | hard | `RC_HARD_260815_03` | **QT05** The Ending Interrogation |
| 6 | Week_4 | hard | `RC_HARD_260815_04` | **QT06** The Compression Test |
| 7 | Week_4 | hard | `RC_HARD_260815_05` | **QT07** Tone Split |
| 8 | Week_4 | elite | `RC_ELITE_260815_01` | **QT08** The Verification Sweep |
| 9 | Week_4 | elite | `RC_ELITE_260815_02` | **QT09** The Decoy Mirror |
| 10 | Week_4 | elite | `RC_ELITE_260815_03` | **QT10** The Silent Partner |
| 11 | Week_4 | elite | `RC_ELITE_260815_04` | **QT11** Local-Global Ladder |
| 12 | Week_4 | elite | `RC_ELITE_260815_05` | **QT12** Structural Emphasis |
| 13 | Week_5 | medium | `RC_MEDIUM_260822_01` | **QT15** The Ambush |
| 14 | Week_5 | medium | `RC_MEDIUM_260822_02` | **QT16** The Load-Bearing Claim |
| 15 | Week_5 | hard | `RC_HARD_260822_01` | **QT13** Evidence Audit |
| 16 | Week_5 | hard | `RC_HARD_260822_02` | **QT14** The Reported Frame |
| 17 | Week_5 | hard | `RC_HARD_260822_03` | **QT17** Application Heavy |
| 18 | Week_5 | hard | `RC_HARD_260822_04` | **QT18** Sequential Dependency |
| 19 | Week_5 | hard | `RC_HARD_260822_05` | **QT19** Purpose First |
| 20 | Week_5 | elite | `RC_ELITE_260822_01` | **QT20** The Half-Turn |
| 21 | Week_5 | elite | `RC_ELITE_260822_02` | **QT21** Deep Drill |
| 22 | Week_5 | elite | `RC_ELITE_260822_03` | **QT22** The Migrating Concept |
| 23 | Week_5 | elite | `RC_ELITE_260822_04` | **QT23** Counterfactual Set |
| 24 | Week_5 | elite | `RC_ELITE_260822_05` | **QT24** The Uniform Field |
| 25 | Week_6 | hard | `RC_HARD_260829_01` | **QT01** The Purpose Frame |

### Copy-paste plan blocks

Send the block for a set, then the file contents, in the same message.

```
RC_MEDIUM_260815_01   (medium)
QUESTION PLAN — QT01 "The Purpose Frame"
Style: difficulty alternates question to question; the purpose question sits mid-set, not at either edge
  Q1: thesis
  Q2: undermine_thesis
  Q3: weaken
  Q4: application
  Q5: primary_purpose
  Q6: except_scan
  Q7: closure_reading
  Q8: detail_check
```

```
RC_MEDIUM_260815_02   (medium)
QUESTION PLAN — QT02 "Classic Gauntlet"
Style: difficulty climbs steadily from the opening thesis to the hardest inference at the close
  Q1: thesis
  Q2: contextual_inference
  Q3: author_vs_reported
  Q4: primary_purpose
  Q5: detail_check
  Q6: except_scan
  Q7: weaken
  Q8: undermine_thesis
```

```
RC_HARD_260815_01   (hard)
QUESTION PLAN — QT03 "Cross-Paragraph Weave"
Style: seven of the eight questions reach across paragraphs — the widest span in the library; only the detail check stays local
  Q1: thesis
  Q2: undermine_thesis
  Q3: evidence_function
  Q4: detail_check
  Q5: counterfactual_structure
  Q6: author_vs_reported
  Q7: except_scan
  Q8: decoy_escape
```

```
RC_HARD_260815_02   (hard)
QUESTION PLAN — QT04 "Inverted"
Style: inverted: the whole-passage question opens the set and the parts are interrogated afterwards, against the reader's already-committed reading
  Q1: thesis
  Q2: closure_reading
  Q3: phrase_in_context
  Q4: detail_check
  Q5: author_vs_reported
  Q6: application
  Q7: structural_function
  Q8: strengthen
```

```
RC_HARD_260815_03   (hard)
QUESTION PLAN — QT05 "The Ending Interrogation"
Style: the closure question comes early and easy; the real weight is back-loaded into the final three
  Q1: thesis
  Q2: closure_reading
  Q3: author_vs_reported
  Q4: stance
  Q5: undermine_thesis
  Q6: structural_function
  Q7: strengthen
  Q8: detail_check
```

```
RC_HARD_260815_04   (hard)
QUESTION PLAN — QT06 "The Compression Test"
Style: long analytical stems, terse options; discrimination lives in the stem
  Q1: thesis
  Q2: closure_reading
  Q3: detail_check
  Q4: undermine_thesis
  Q5: stance
  Q6: contextual_inference
  Q7: primary_purpose
  Q8: application
```

```
RC_HARD_260815_05   (hard)
QUESTION PLAN — QT07 "Tone Split"
Style: the stance question anchors a set of otherwise even, moderate demands
  Q1: thesis
  Q2: structural_function
  Q3: application
  Q4: detail_check
  Q5: weaken
  Q6: strengthen
  Q7: contextual_inference
  Q8: stance
```

```
RC_ELITE_260815_01   (elite)
QUESTION PLAN — QT08 "The Verification Sweep"
Style: rewards the reader who verifies against the text rather than recognises
  Q1: thesis
  Q2: application
  Q3: undermine_thesis
  Q4: closure_reading
  Q5: except_scan
  Q6: detail_check
  Q7: primary_purpose
  Q8: strengthen
```

```
RC_ELITE_260815_02   (elite)
QUESTION PLAN — QT09 "The Decoy Mirror"
Style: the planted misreading is not sprung until late — the reader has to have committed to it first
  Q1: thesis
  Q2: contextual_inference
  Q3: phrase_in_context
  Q4: strengthen
  Q5: decoy_escape
  Q6: primary_purpose
  Q7: detail_check
  Q8: counterfactual_structure
```

```
RC_ELITE_260815_03   (elite)
QUESTION PLAN — QT10 "The Silent Partner"
Style: the author's unstated commitments surface only as the questions climb
  Q1: thesis
  Q2: structural_function
  Q3: closure_reading
  Q4: undermine_thesis
  Q5: contextual_inference
  Q6: detail_check
  Q7: stance
  Q8: author_vs_reported
```

```
RC_ELITE_260815_04   (elite)
QUESTION PLAN — QT11 "Local-Global Ladder"
Style: alternates local reading and cross-passage reach, rung by rung
  Q1: thesis
  Q2: detail_check
  Q3: author_vs_reported
  Q4: strengthen
  Q5: undermine_thesis
  Q6: structural_function
  Q7: phrase_in_context
  Q8: application
```

```
RC_ELITE_260815_05   (elite)
QUESTION PLAN — QT12 "Structural Emphasis"
Style: why each move was made matters more than what it says; uniformly high demand
  Q1: thesis
  Q2: phrase_in_context
  Q3: author_vs_reported
  Q4: application
  Q5: contextual_inference
  Q6: closure_reading
  Q7: structural_function
  Q8: detail_check
```

```
RC_MEDIUM_260822_01   (medium)
QUESTION PLAN — QT15 "The Ambush"
Style: five gentle questions, then the last three turn sharply — nothing in the rhythm warns of it
  Q1: thesis
  Q2: author_vs_reported
  Q3: except_scan
  Q4: application
  Q5: weaken
  Q6: detail_check
  Q7: closure_reading
  Q8: evidence_function
```

```
RC_MEDIUM_260822_02   (medium)
QUESTION PLAN — QT16 "The Load-Bearing Claim"
Style: isolates the one claim the argument cannot lose, then attacks it from several sides
  Q1: thesis
  Q2: detail_check
  Q3: evidence_function
  Q4: undermine_thesis
  Q5: weaken
  Q6: application
  Q7: phrase_in_context
  Q8: strengthen
```

```
RC_HARD_260822_01   (hard)
QUESTION PLAN — QT13 "Evidence Audit"
Style: the set audits what work each piece of evidence is doing; even, moderate difficulty throughout
  Q1: thesis
  Q2: evidence_function
  Q3: decoy_escape
  Q4: phrase_in_context
  Q5: weaken
  Q6: contextual_inference
  Q7: strengthen
  Q8: detail_check
```

```
RC_HARD_260822_02   (hard)
QUESTION PLAN — QT14 "The Reported Frame"
Style: the author's own view has to be separated from the views being staged
  Q1: thesis
  Q2: closure_reading
  Q3: evidence_function
  Q4: undermine_thesis
  Q5: except_scan
  Q6: detail_check
  Q7: author_vs_reported
  Q8: decoy_escape
```

```
RC_HARD_260822_03   (hard)
QUESTION PLAN — QT17 "Application Heavy"
Style: new scenarios and staged voices dominate; two difficulty peaks rather than a climb
  Q1: thesis
  Q2: contextual_inference
  Q3: phrase_in_context
  Q4: evidence_function
  Q5: weaken
  Q6: application
  Q7: strengthen
  Q8: detail_check
```

```
RC_HARD_260822_04   (hard)
QUESTION PLAN — QT18 "Sequential Dependency"
Style: later questions reward insight built answering earlier ones
  Q1: thesis
  Q2: detail_check
  Q3: counterfactual_structure
  Q4: undermine_thesis
  Q5: primary_purpose
  Q6: application
  Q7: phrase_in_context
  Q8: contextual_inference
```

```
RC_HARD_260822_05   (hard)
QUESTION PLAN — QT19 "Purpose First"
Style: the hardest work is front-loaded; the set relaxes as it goes
  Q1: thesis
  Q2: closure_reading
  Q3: weaken
  Q4: detail_check
  Q5: undermine_thesis
  Q6: primary_purpose
  Q7: author_vs_reported
  Q8: phrase_in_context
```

```
RC_ELITE_260822_01   (elite)
QUESTION PLAN — QT20 "The Half-Turn"
Style: the argument is turned half-way and held there; difficulty zigzags across the set
  Q1: thesis
  Q2: detail_check
  Q3: except_scan
  Q4: evidence_function
  Q5: weaken
  Q6: application
  Q7: author_vs_reported
  Q8: strengthen
```

```
RC_ELITE_260822_02   (elite)
QUESTION PLAN — QT21 "Deep Drill"
Style: two questions drill the same dense material from different angles
  Q1: thesis
  Q2: weaken
  Q3: evidence_function
  Q4: contextual_inference
  Q5: undermine_thesis
  Q6: detail_check
  Q7: author_vs_reported
  Q8: stance
```

```
RC_ELITE_260822_03   (elite)
QUESTION PLAN — QT22 "The Migrating Concept"
Style: one concept is tracked as its sense migrates across the passage; difficulty rises with the drift
  Q1: thesis
  Q2: detail_check
  Q3: phrase_in_context
  Q4: weaken
  Q5: application
  Q6: contextual_inference
  Q7: structural_function
  Q8: closure_reading
```

```
RC_ELITE_260822_04   (elite)
QUESTION PLAN — QT23 "Counterfactual Set"
Style: what the argument would lose if a part were removed; the demand climbs to the close
  Q1: thesis
  Q2: contextual_inference
  Q3: detail_check
  Q4: strengthen
  Q5: counterfactual_structure
  Q6: phrase_in_context
  Q7: primary_purpose
  Q8: closure_reading
```

```
RC_ELITE_260822_05   (elite)
QUESTION PLAN — QT24 "The Uniform Field"
Style: eight questions of identical moderate difficulty — no rhythm cue about where the danger is
  Q1: thesis
  Q2: strengthen
  Q3: weaken
  Q4: contextual_inference
  Q5: phrase_in_context
  Q6: structural_function
  Q7: detail_check
  Q8: author_vs_reported
```

```
RC_HARD_260829_01   (hard)
QUESTION PLAN — QT01 "The Purpose Frame"
Style: difficulty alternates question to question; the purpose question sits mid-set, not at either edge
  Q1: thesis
  Q2: undermine_thesis
  Q3: weaken
  Q4: application
  Q5: primary_purpose
  Q6: except_scan
  Q7: closure_reading
  Q8: detail_check
```
