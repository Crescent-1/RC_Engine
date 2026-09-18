# Revision Changelog — Week 9 (10 papers)

Built 2026-09-14 for the 19 Sep send. Sources: the unshipped AA bench (DB `approved` /
`needs_review`, minus everything in `sent_index.json` and the `..\RC` week folders).
Originals in `exported_rc_sets/` root and `flagged_similar/` are unmodified; these are copies.

Brief from Ansh: philosophy- and literature-heavy week. 8 of 10 papers are philosophy or
literature; the two medium fillers (0056, 0054) were Ansh's choice over the manual pilot sets.

Two passes: (1) the QA-checklist pass on questions and options, (2) a house-voice pass on the
passages under the anchor-lock brief Ansh gave Gemini, done here with scripted checks instead.

---

## Final state

| Paper | Subject | Words | Qs | Letters | Correct longest / shortest | Worst spread |
|---|---|---|---|---|---|---|
| RC-ELITE-260711-0024 | Philosophy: fairness and officiating technology | 543 | 8 | 2/2/2/2 | 0 / 0 | 1.16× |
| RC-ELITE-260811-0039 | Literature: plain style and critical authority | 527 | 8 | A3 B2 C2 D1 | 1 / 1 | 1.21× |
| RC-ELITE-260914-0087 | Literature: Bajza and the first Slovak novel | 549 | 8 | 2/2/2/2 | 1 / 0 | 1.17× |
| RC-HARD-260811-0037 | Philosophy: the ethics of whistleblowing | 545 | 8 | A2 B2 C1 D3 | 0 / 2 | 1.26× |
| RC-HARD-260811-0047 | Literature: a family-saga trilogy | 525 | 8 | 2/2/2/2 | 0 / 0 | 1.16× |
| RC-HARD-260914-0099 | Philosophy: anti-natalism in Japan | 540 | 8 | A3 B2 C1 D2 | 0 / 0 | 1.13× |
| RC-MEDIUM-260726-0021 | Philosophy: blaming the dead | 532 | 8 | 2/2/2/2 | 0 / 0 | 1.19× |
| RC-MEDIUM-260914-0074 | Philosophy/literature: Genesis 22 and Boehm | 506 | 8 | 2/2/2/2 | 0 / 0 | 1.16× |
| RC-MEDIUM-260904-0056 | Policy: child-protection reporting | 542 | 8 | 2/2/2/2 | 0 / 1 | 1.16× |
| RC-MEDIUM-260901-0054 | Arts: museum labels | 518 | 8 | A3 B1 C2 D2 | 2 / 0 | 1.25× |

Every paper passes every rule in `2026-09-07-rc-qa-checklist.md` (R1–R6, B1–B3, C, D, E, F),
re-measured from the final files. No run of one letter longer than two anywhere.

---

## 1. Selection

72 unshipped AA sets were on the bench (20 approved, 52 needs_review). None shares passage text
with anything shipped. Excluded from a phil/lit week:

- **Too close to something the client already has.** ELITE-0822-0060 and MEDIUM-0914-0070 (near
  W5's MEDIUM-0822-0034); HARD-0822-0062 (near W5's MEDIUM-0822-0037); MEDIUM-0901-0055 and
  HARD-0904-0080 (the "three categories rejected" structure of W7's ELITE-0901-0071; 0080's screen
  note names a non-existent HARD-0901-0071, but its stated reason is W7's paper).
- **ELITE-0822-0062**: green on structure, but the same digital-remains ground as W8's HARD-0822-0060.
- **The Sept 14 pilot sets flag each other** (0086↔0070/0089/0074, 0087↔0091, 0099↔0089,
  0076↔0074), so at most one of each flagged pair is in the week.

---

## 2. QA pass (questions and options)

**10 new questions written, 1 assumption question removed, 39 options capitalised, 36 full stops
added.** Every retained question keeps its original correct letter (checked programmatically).

| Paper | Work |
|---|---|
| 0024 | 6Q → 8Q: +Q7 analogous case (C), +Q8 EXCEPT (D). Passage 414 → 529 (three sentences inside existing paragraphs). Q1/Q3/Q4 rebalanced; Q4 was 1.44× with the correct answer longest |
| 0039 | Q8 was a second weaken item → role of the final paragraph (C). Q3/Q5/Q6/Q7 rebalanced. Q4 key misquote fixed |
| 0087 | Q5 was a second weaken item → likely-to-disagree (A). Q7 distractor D rewritten (the judge's weakest trap). Q3/Q7/Q8 rebalanced |
| 0037 | Q2 rebalanced (1.35×, correct answer shortest) |
| 0047 | Garbled sentence fixed ("and quoted it everyone has since"). Passage 496 → 519. Q8 stem no longer says "steelman". Six questions rebalanced (worst 1.41×). Two key misquotes fixed |
| 0099 | Passage 563 → 544. Q3 was a second EXCEPT item overlapping Q8 → strengthen (D). Q2 stem de-jargoned. Five questions rebalanced |
| 0021 | 6Q → 8Q: assumption-stem Q4 → weaken (C), +Q7 analogous case (B), +Q8 function of an example (D). All options rebalanced (correct answer was shortest in 6/6, spread 1.60×). Q3's correct option said "blame" where the passage says "sanction" |
| 0074 | Q5 was a second EXCEPT item → phrase in context (D). Six questions rebalanced |
| 0056 | Q2 was a second weaken item → analogous case (C). Q4/Q7/Q8 rebalanced |
| 0054 | Q1/Q7 spreads fixed; Q5 correct-shortest fixed; Q3(C) was a claim about the author inside an "if true" question, now a finding |

---

## 3. House-voice pass (passages)

### Method

The brief: lock every quoted phrase, vary openings, remove ledger metaphors unless load-bearing,
break the long-clause-then-punchline cadence, vary the "both camps miss it" transition. Done here as:

- **Anchor lock by script.** Every quoted string in any stem, option or key line was extracted
  and required verbatim in the new passage; a write was refused if one went missing. 0074's Q7
  stem quotes a whole sentence the extractor cannot parse, so it was checked by exact match.
- **Paragraph count and roles fixed.** Keys cite paragraphs by number; each paragraph keeps its job.
- **Paraphrase dependencies read by hand.** For example, 0099's ¶1 must still close on both
  camps assuming the sentence is about the world (Q6), and 0021's ¶3 must still call the
  concession a conclusion that "moves too fast" near its close (Q5).
- **500–550 enforced on every write**; stock transitions ("Moreover", "Ultimately", "In reality",
  "From this perspective") refused.
- **Headers, questions, keys and the source line are byte-identical** to the QA-pass files.

### Per paper

| Paper | Locked anchors | Register | Removed or changed |
|---|---|---|---|
| 0024 | 13 | Sports columnist, "we" | Throat-clearing opening; "The cameras took that away. They were supposed to."; "The shrug is gone."; "We did not."; "Watch it —"; "The exchange is exact" |
| 0039 | 9 | Critic arguing through questions | "Tea-stained memo" prop opening; "Plain writing surrenders it."; "Say what you mean."; "But consider…". Debt close kept: Q8 and Q1 keys quote it |
| 0087 | 9 | Archival historian | Definition opening now opens on the 1783 event; "Not a title page."; "What survives is thin."; the chain "Contested, then unsold. Unsold, then unfunded. Part three abandoned."; "Return to the Pressburg shop."; both "nobody" lines |
| 0037 | 10 | Legal-affairs reporter | Verbless prop-zoom opening; "Consider the accountants…"; markdown `*did you lie*` now quoted questions. "That verdict stands" and "The bill for it is presented separately" kept: Q3 key and Q7 stem |
| 0047 | 18 | First-person reviewer | "Read the three volumes…" and "Look again…" imperatives; "The phrase sits well."; "it costs exactly what it is praised for possessing" |
| 0099 | 5 | Past-tense reporting | "I think both have mislaid the subject."; "The word is the tell."; the "One camp… The other… Both assume" triplet. The remaining "two camps" lines are quoted by Q2/Q6 |
| 0021 | 10 | Moral philosopher | 1911 brass-plate prop opening; staccato ¶4 "It is not. Blame has an audience. Always did."; "They cannot recant. They cannot be rehabilitated."; "discount" and "transaction voids"; `*otherwise*`, `*sanction*` asterisks |
| 0054 | 3 | Museum studies | "Fifty words on a raked card" prop opening; "The instances do not line up."; "The two camps take themselves… They are not."; `*label*` asterisks |
| 0056 | 2 | Policy report, shorter sentences | "Consider one sequence."; "Triage sorts it."; "This is careful clockwork."; "Limits matter here."; "The verdict follows from that."; "fix all four" (a list of three) |
| 0074 | 9 + Q7 sentence | Critic, "we" as readers | Catalogue opening; "it can be described step by step"; "The surface clarity has a cause."; "The price is exact." |

### Measured, before → after (same method as the Aug 29 batch comparison)

| Measure | Before | After | Shipped W5–W8 |
|---|---|---|---|
| Sentences of 4 words or fewer | 29 | 3 | — |
| Long sentence then punchline | 11 | 2 | — |
| Reader-directed imperatives | 6 | 1 | — |
| "nobody" / "no one" | 3 | 0 | — |
| Voice markers, mean per paper (of 7) | 2.9 | **1.6** | 2.4–3.0 |
| Function-word cosine, mean pairwise | 0.9161 | 0.9160 | 0.907–0.925 |
| 8-word sequences shared with any shipped passage | 0 | 0 | — |
| 5-word sequences repeated inside the batch | 0 | 0 | — |

All three remaining punchlines are quoted by a stem ("I believed that phrase once. I said it
warmly."; "This is not neutrality."). Every remaining voice marker is either quoted by a question
or a false positive ("the surviving record"; "concede it", about a goal; "I grant" in 0074's
locked Q7 sentence).

**The function-word cosine did not fall.** A first version of this pass pushed it to 0.923:
removing every short sentence moved all ten passages toward the same long, clause-heavy syntax.
Registers were then pulled apart deliberately (0024 conversational, 0039 interrogative, 0056
report-like), which brought it back to 0.916. Expository prose shares its commonest function
words, so this proxy barely moves without distorting the writing; it was not forced further.

### What this pass cannot change

The four-step skeleton (claim, complication, reframing, named cost) is partly written into the
questions: Q8s ask about the final paragraph, 0099's Q7 about how the passage ends, 0074's Q8
quotes the closing price. Openings, transitions and cadence now differ paper to paper; the
endings stay close to the originals because the keys cite them. Changing that means rewriting
those questions.

---

## 4. Versus the Gemini runs (read from the two Gemini chats, 2026-09-14)

Gemini revised 8 of the 10 (0047 and 0099 were never done). Against the same brief:

- **Length.** 4 of its 8 passages break 550: 0054 577, 0021 571, 0087 567, 0056 567 (counted
  after removing its citation markers, which had inflated 0087 to 589 and 0037 to 563).
- **Headers.** Its 0087 and 0037 headers read `Status: approved | Compliance F1: 1.0`; the DB has
  both as `needs_review` (0087 F1 0.862).
- **Artifacts.** `[cite: N]` markers through the 0087 and 0037 passages and keys (53 and 55).
- **Anchor lock broken in the keys.** Key lines for 0087 Q2/Q5/Q7 and 0037 Q2/Q3 were edited
  (quote punctuation moved), despite the lock.
- **New errors.** 0056: "the study could name the desk it stalled at whenever a case languished"
  loses the antecedent of "it". 0024: dropping "I used to argue this" leaves "my old argument" in
  ¶3 without a referent.
- **Register.** Tics were replaced with a uniform academic voice ("In reality", "From this
  perspective", "Understood in this light", "a distinct structural transaction").

---

## 5. Cold solve after the voice pass (2026-09-15)

Two independent solvers worked from key-free packets with shuffled neutral IDs (P01–P10) and
answered all 80 questions against the voice-pass passages.

**Agreement with the keys: 80/80** (76 certain, 4 leaning). No key was wrong. The solvers also
audited each paper. Each of the five flags was read against its passage and key; all five hold up.

| Paper | Q | Flag | Verdict | Fix |
|---|---|---|---|---|
| 0087 | Q7 | Two defensible (D) | Introduced by the QA pass. The rewritten D ("the eventual loss of funding was what finally closed it") follows the passage's own order: unsold, unfunded, abandoned | D names the rival's attack on the spelling instead. ¶3 puts that before the lost sales, and the key now quotes "a layered one" |
| 0087 | Q5 | Guessable | Also QA-pass work: A was the only absolute ("altogether") | A drops it ("clerics no longer read the manuscripts submitted for review"). D takes a negation the passage supports ("did not quarrel over the book's design, only over its surface details") |
| 0087 | — | Passage (raised in the Q7 note) | ¶2 warns against chaining the four surviving items; ¶3 then states a chain. Already in the engine original | ¶3 opens "Context supplies a cause for the stall, though a layered one." |
| 0054 | Q2 | None defensible | Engine original. "Queried more often" can signal distrust, so D never showed a label earning credit | D: "visitors trust labels that cite sources more than neutral-sounding ones" |
| 0039 | Q6 | Guessable | Engine original. In this EXCEPT item, the hidden-motive option was the only one in a different register | D says examples are too few, in the register of A–C. ¶1 contradicts it ("its champions have never lacked for examples") |
| 0056 | Q6 | None defensible | Engine original. The passage never said why the study could name the desk | ¶4: "the cross-checked records let the study name the desk". Key (B) now cites ¶4 |

- **Leaning answers without a flag.** 0074 Q4 is sound: B is the illustration-not-machinery view
  the passage argues against.
- **Rationale drift, found while reading 0087.** The voice pass removed "joint" from ¶3, but two
  rationales still used it. They now say "pressure" and quote "narrowed what came next".
  `drift_check.py` lists rationale words that were in the pre-voice passage and are gone from the
  current one: 44 hits, the rest ordinary paraphrase. The five hits that could matter (0099 Q2,
  Q6 and Q8, 0021 Q2, 0054 Q6) were read against their passages and still hold.
- **After the fixes.** No key letter changed. All ten papers re-measured: 0 checklist issues. The
  passage edits went through the anchor guard: 0087 549 words, 0054 518, 0056 542. The four
  docx files were rebuilt and `check_docx.py` passes on all ten.
- **Re-check of the edited items.** A blind re-solve of the four edited papers stalled; the
  solver never got past its first step. It was stopped at Ansh's request, and the five edited
  questions were re-read against their passages instead. Each has exactly one defensible
  answer. No independent solver has seen the edited wording.

---

## Verification performed

- Per paper: QA checklist re-measured from the final files; 0 issues on all ten.
- Anchors: all 90 locked strings present verbatim (the post-solve keys added two); 0074 Q7
  sentence exact-matched.
- Outside the passage, every file is byte-identical to its pre-voice-pass copy, except for the
  post-solve question and key edits in section 5 (0087, 0039, 0054, 0056).
- Paragraph counts unchanged on all ten.
- Overlap with all 91 shipped passages (`sent_index.json`): none at 8 words.
- Cold solve of all 80 questions after the voice pass: 80/80 (section 5).

## Staged and recorded (2026-09-15)

- **Week 9 folder.** `..\RC\Week_9_19_09` holds the ten docx files, flat like Week 8:
  - RC_ELITE_260919_01–03: 0024, 0039, 0087
  - RC_HARD_260919_01–03: 0037, 0047, 0099
  - RC_MEDIUM_260919_01–04: 0021, 0054, 0056, 0074

  Each file is byte-identical to its export docx, and its text equals the working .txt. Package
  parts, paragraph properties, section settings and line order match the Week 8 files. The
  empty July scaffold folders were removed with Ansh's approval.
- **Both trackers rebuilt.**
  - `RC_Shipping_Tracker.xlsx`: Week 9 is "staged, not yet emailed", all ten sets match their
    passages exactly, and they are off the bench.
  - `..\RC\RC_Shipped_Sets.xlsx`: Week 9 (19 Sep) added.
  - Weeks 1–8 rows are unchanged from the Sep 12 build in both files. The bench also picked up
    17 pilot exports from Sep 12–14, which have no genre yet.
- **Weeks 6–7 folder fix.** `Week_6_29_08` and `Week_7_05_09` had been nested inside
  `Week_5_22_08` since Sep 14 17:30, so both trackers showed Weeks 6–7 as unfiled. Both folders
  were moved back to the RC root with Ansh's approval; their contents are unchanged.

## Not done

- **No independent solve of the five edited questions** (see section 5).
- **No render check.** The formatting was compared against Week 8 at the XML level; the files
  were not opened in Word.
- **Left untouched.** DB statuses are unchanged, and there is no `Week_9_19_09.zip` (Week 8's
  was made at send time).
- **After mailing.** Rebuild `sent_index.json`, then both trackers, so Week 9 reads "emailed".
- **Leftover temp file.** `docx/RC-MEDIUM-260901-0054.docx.tmp` remains from a write that an
  open Word window blocked.
