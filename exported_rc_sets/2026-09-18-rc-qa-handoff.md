# Handoff: RC paper QA

Written for whoever picks this up next. The `rc-paper-qa` skill has the rules and thresholds; this is the part that doesn't fit in a rulebook — what the rules are *for*, where I got things wrong, and what to be suspicious of.

---

## What this is

Ansh runs a generator that produces reading-comprehension papers for eLitmus aptitude testing. It emits `.txt` files; candidates eventually see `.docx`. Your job is quality control between those two points, and it is adversarial work: you are looking for ways a candidate could score without reading the passage, and for keys that are wrong.

He gave four requirements at the start and added two more after feedback. Everything else in the checklist exists because something got past those six.

**Where things live** (Windows, via the device bridge):

- `RC Gen Project\exported_rc_sets\` — the generator's output pool. Root holds most papers; `flagged_similar\` holds others; dated subfolders hold past revisions.
- `RC Gen Project\exported_rc_sets\<YYYY-MM-DD>-<name>\` — where revisions go, with a `docx\` subfolder and a changelog.
- `RC\Week_N_DD_MM\` — the weekly delivery folders, **docx only**. Named for the Friday: Week_7 is `05_09`, Week_8 `12_09`, Week_9 `19_09`.
- Only some folders are connected at any time. `RC\` itself needed a `device_request_folder_access` call before I could create Week 8 inside it.

---

## The one thing to internalise

**A paper can satisfy every stated rule and still be unusable.**

Week 8 had three papers where the correct answer was the longest option in every question, or the shortest in every question — 6 of 6, three times over. Eighteen questions answerable by a candidate who never read the passage. Every one of those papers passed "options of comparable length" as a naive reading of it, and all three scored 8.4–8.6 from the project's own judge.

That is why the checklist has three option-length tests and not one. Spread catches a single outlier. **Position** catches the thing that actually breaks a paper.

Measure it every time. It costs four lines.

---

## What the judge score is worth

Nothing, for your purposes. Treat it as orthogonal.

- A paper scoring **9.2** and marked `approved` carried a 1.36× spread with the correct answer shortest on its main-idea question.
- In Week 8 the only fully clean paper had the **lowest** score in the batch (7.6). The highest (8.8) failed.

Don't let a high score soften your reading, and don't assume a low score means a bad paper.

---

## Solve first. Actually first.

Extract passage + questions, answer all eight, *then* open the key. Not alongside. The discipline is the whole value — once you have seen the key you cannot un-see it, and you will rationalise.

Across ~230 questions I have solved this way, the key was right essentially every time. Four disputes, all four resolved in the key's favour. **But every dispute pointed at a real weakness in the item** — a distractor that was defensible, an option whose wording fought the stem. So a mismatch is not "I was wrong, move on". It is a flag to examine the item.

**For questions you write yourself, self-review is not enough.** Hand them to a subagent with the passage and the options and no key, and ask it to be adversarial. On the ten questions I wrote for Week 8 it confirmed all ten answers *and* found three real defects I had missed:

- an option 4–5 words longer than every distractor that also echoed the passage's distinctive phrasing — guessable twice over;
- the longest option on an EXCEPT stem, resting on a passage sentence that was genuinely ambiguous;
- a credited "weaken" option that undermined the author's description of current practice rather than his conclusion.

I would not have caught any of those reading my own work.

---

## Mistakes I made — expect to repeat them

**I introduced an answer-letter run while adding questions.** One paper briefly ran A, A, A, A. Rebalancing options and adding items is exactly when clustering creeps in. Check the letter distribution *after* every edit, not once at the end.

**I over-corrected an option length** and flipped a question from correct-is-shortest to correct-is-longest. Measure after every adjustment; the fix creates the mirror-image defect if you overshoot. Iterate numerically rather than eyeballing.

**I trusted file modification times to date exports.** Every file in the folder carried an identical bulk-resync mtime and the dating was meaningless. Use the `Generated:` timestamp inside the file header.

**I nearly repeated a claim from the project's own manifest.** It stated a stylistic tic appeared in paper 0037; a grep showed it in 0033, 0034 and 0039 and *not* 0037. The project's own notes are evidence, not fact — verify before repeating.

**Small technical traps:** the Edit tool refuses a file you have not Read this session, which bites on freshly copied files. `device_bash` reported "Workspace unavailable" on this machine throughout — stage files into the container and work there instead. `device_commit_files` returns HTTP 404 for `stagedPath`; pass the `fileUuid` from a prior `SendUserFile`. Commit paths must sit inside a *connected* folder or they are refused. The bridge dropped mid-task once; `/tmp` survived and the work continued locally until it returned.

---

## Generator habits worth watching

These recur. Finding them again is not a surprise; finding them *absent* is the surprise.

| Habit | Status |
|---|---|
| Central-idea **and** primary-purpose question in one paper | Six consecutive batches. Passes only if the purpose option is about rhetorical *method*, not a restatement. |
| Assumption questions | Two stem forms seen: "would best license the inference" and "depends on which unstated assumption". Assume a third exists. |
| Option register split by stem punctuation | Colon-ending stems get lowercase fragments; question-mark stems get capitalised sentences. This is what generated ~200 formatting violations per batch. |
| Passage overshoot | Usual failure. But Week 8 produced two passages *under* 500 for the first time, which is harder to fix well. |
| Six-question papers | Anything generated in July predates the eight-question standard. Check the count before anything else. |

**Mixing old material into a current set is where the damage comes from.** Every structural failure in Week 8 traced to the four July papers. The September papers in the same batch needed only minor option work. If you see a set reaching back more than a few weeks, say so early — it changes what the job is.

---

## A separate thread: voice sameness

Not one of the six rules, but it is the finding I am most confident mattered.

The project ran a "house-voice fix". It made the papers *more* alike, not less: marker density went 2.4 → 4.8 of 7 per paper, intra-batch cosine 0.9000 → 0.9219. The manifest logged the same intervention as a success ("adherence 33% → 78%") — the number recording the win and the number recording the defect are the same number.

It broke on 1 September: markers back to 2.9, cosine 0.8955, and papers started reaching verdicts instead of all ending in the same withheld non-conclusion.

Two cheap metrics catch this where the novelty channel cannot: marker density below 2 of 7, and mean pairwise function-word cosine below 0.88.

---

## Working with Ansh

Terse instructions, high trust, acts on direct findings. He does not want hedging — when I said three papers were unusable as test items, the reply was "fix length, add cat relevant questions, fix option length bias, I need to use these sets." That last clause is the important one: **he wants the papers usable, not replaced.** I had offered to swap the broken July papers for cleaner September material and he declined. Don't re-offer a shortcut he has turned down.

His standing instructions: never modify originals, write revisions to a new dated folder, name files `YYYY-MM-DD-descriptive-name`, outline a plan before multi-step work, and list what you created at the end.

Ask before starting only when the scope changes what is worth doing — as when a fix would mean writing ten new questions. Otherwise proceed and report.

---

## Open, never resolved

1. **Retrofitting the two formatting rules to the five earlier revised folders.** They are violated there just as widely. I raised it twice; no answer either time. Worth asking once more, not three times.
2. **Whether the colon-ending stems should be rewritten as questions** so the capitalised options read naturally. Right now "…is described as: **(A) Necessary** for verification…" is correct per the rule and slightly odd to read. It is a real editorial choice and it is his to make.
3. **Whether any of this moves into the generator.** Four things would pay for themselves immediately: the length-position check, the assumption regex with both forms, the two formatting rules at export, and a warning on the gist + purpose pair. I have raised this every batch. It has not happened, and the weekly cleanup keeps costing more than the fix would.

---

## If you do nothing else

Solve the questions yourself before reading the key. Measure whether the correct answer sits at the extreme of the length range. Those two habits found every serious defect in eight weeks of this work; everything else in the checklist is bookkeeping.
