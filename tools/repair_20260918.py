"""Rebuild the eight September 18 exports as separate, locally checked candidates.

No engine, database, tracker, source export, or paid API is modified.
Run from the repository root. All option edits below use ORIGINAL letters;
relettering occurs only after text and rationale changes are complete.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "exported_rc_sets/2026-09-19-sept18-repaired"
LETTERS = "ABCD"


def parse(path):
    text = path.read_text(encoding="utf-8")
    front, rest = text.split("[PASSAGE]\n\n", 1)
    passage, rest = rest.split("\n\n[QUESTIONS]\n\n", 1)
    questions, rest = rest.split("\n\n[ANSWER KEY & ELIMINATION LOGIC]\n\n", 1)
    key, source = rest.rsplit("\n\n[Inspired by:", 1)
    qs = []
    blocks = re.split(r"\n\n(?=Q\d+ —)", key.strip())
    question_blocks = re.split(r"\n\n(?=Q\d+\.)", questions.strip())
    assert len(question_blocks) == len(blocks) == 8
    for qblock, kblock in zip(question_blocks, blocks):
        n, stem = re.match(r"Q(\d+)\. (.+)", qblock).groups()
        assert int(n) == len(qs) + 1 == int(re.match(r"Q(\d+)", kblock)[1])
        correct = re.search(r"Correct answer: \(([A-D])\)", kblock)[1]
        options = dict(re.findall(r"^\(([A-D])\) (.+)$", qblock, re.M))
        reasons = dict(re.findall(r"^  \(([A-D])\) (.+)$", kblock, re.M))
        assert set(options) == set(reasons) == set(LETTERS)
        qs.append(dict(n=int(n), stem=stem, options=options, correct=correct, reasons=reasons))
    assert len(qs) == 8
    return dict(id=path.stem, tier=re.search(r"Tier: (\w+)", front)[1], passage=passage,
                questions=qs, source="[Inspired by:" + source, path=path,
                original_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def opt(s, n, letter, value):
    s["questions"][n-1]["options"][letter] = value


def reason(s, n, letter, value):
    s["questions"][n-1]["reasons"][letter] = value


def trim(s, old, new):
    assert s["passage"].count(old) == 1, old
    s["passage"] = s["passage"].replace(old, new)


paths = sorted((ROOT / "exported_rc_sets").glob("*260918*.txt"))
paths += sorted((ROOT / "exported_rc_sets/flagged_similar").glob("*260918*.txt"))
sets = {p.stem[-4:]: parse(p) for p in paths}
assert set(sets) == {"0093", "0102", "0077", "0078", "0080", "0081", "0082", "0103"}

# Preserve the passages' substantive claims and every question's answer logic,
# except the explicitly replaced 0081 Q5 and 0103 Q8.
s = sets["0093"]
s["tier"] = "hard"
trim(s, "an engineering draughtsman then out of regular work with the Underground", "an engineering draughtsman")
trim(s, "The public took it within weeks and asked for more.", "The public quickly asked for more.")
trim(s, "They descend, they wait, they ride two stops, they climb, and they arrive where walking would have brought them sooner.", "They descend, wait, ride two stops and climb, arriving where walking would have brought them sooner.")
trim(s, "which is the whole of what several million people used to move, daily, beneath streets it declined to draw", "which several million people used daily beneath streets it declined to draw")
s["questions"][0]["stem"] = "Which one of the following best states the primary purpose of the passage?"
opt(s, 1, "C", "To assess a single-question diagram's honesty and why borrowed versions can forfeit it.")

s = sets["0102"]
trim(s, "the petitioner's obligation to write down something the other spouse did, and to have it believed, before the court will open the door", "the petitioner's obligation to state and establish something the other spouse did before the court will act")
trim(s, "Each fact reads like a ground in its own right, and was argued over as if it settled what the marriage had contained.", "Each fact reads like a separate ground and was argued over accordingly.")
opt(s, 1, "B", "England kept fault as a genuine ground for divorce, making its 1969 statute more conservative in principle than California's.")
opt(s, 2, "C", "A searching route for difficult petitions, requiring closer judicial scrutiny of their stated particulars.")
opt(s, 2, "D", "A reform introduced in 1977 that replaced the five statutory facts with one statement of breakdown.")
opt(s, 3, "B", "A fixed waiting interval imposed after filing, rather than evidence that the marriage has broken down.")
reason(s, 3, "B", "CORRECT — Paragraph four distinguishes separation lived through as evidence before filing from the fixed waiting interval imposed after filing; the latter does not establish breakdown.")

s = sets["0077"]
s["tier"] = "hard"
s["passage"] = '''A dolphin can matter to a household as a person with intentions rather than an animal with a distribution. That distinction troubles the index I helped build. In it, "dolphin conflict" means one thing: a reportable encounter in which a river dolphin causes physical damage, injury, or a documented loss of catch. That is a clean definition. It has to be. A torn gillnet can be photographed, priced, entered. A bite can be dated. I defended that discipline for three seasons and would defend most of it now. The difficulty is whether a record of material incidents can also register the relation within which people decide what to do.

My first instinct was a new column. A colleague who has run more river surveys than I will said the thing that stopped me: an account of a dolphin who comes ashore in a white shirt and follows a woman home is not evidence unless you can tie it to an observable event. He was defending something real. Our index works the way an airport checkpoint works: it inspects with great accuracy whatever is carried through its gates, and it has no way to register the bag that was repacked at home, the corridor nobody walks any more, the warning a grandmother passed to a child about a room she herself never entered. Those absences are not measurements of a species. They are records of a relation.

Consider a family on a middle stretch of the Caquetá. They stopped bathing at a landing used for two generations because a dolphin surfaced there twice and an older woman read the surfacing as a warning. No net was lost. Nobody was touched. The index recorded nothing, and it was right to record nothing, and a household's day had been rebuilt around the silence. What the Andoque record holds is a danger that runs both ways: a dolphin's capacity to invite, to seduce, to punish a discourtesy alters conduct weeks before anything countable happens. The absent object is that agency. Adding a hundred more anecdotes would not supply it. Rankings set patrol routes, gate compensation and inform protected boundaries; yet my complaint concerns what the index can represent, not merely its administrative use.

None of this comes free. A survey that asks what people stopped doing, and why, runs several times longer than one that counts nets, and its categories no longer line up across rivers. Money moves more easily when harm arrives as a figure. An officer hearing an account of a visit, a warning and an abandoned landing spends an afternoon that converts into no score. I still think the index owes an answer for what it leaves out, rather than Andoque households owing proof that their dolphins behave as they say. They have been asked for years to render a relation as damage, and the rendering discards precisely the part that governs conduct. The burden sits better with whoever insists the exclusion is harmless, a position that has been assumed far more often than it has been argued.'''
opt(s, 1, "A", "An index of material incidents misses the dolphin's attributed agency; the author contests that omission while defending the index's accuracy.")
opt(s, 3, "C", "The rankings' effects on patrols and payments make bureaucratic injustice, rather than attributed personhood, the underlying issue.")
opt(s, 5, "B", "Households change fishing and bathing only after countable incidents; their stated reasons follow the damage rather than preceding it.")
opt(s, 6, "D", "It turns the colleague's reasonable objection into an account of the index's limits, distinguishing accurate measurement from complete coverage.")
reason(s, 1, "A", "CORRECT — The opening distinguishes attributed personhood from material incidents; the checkpoint analogy sets a limit on accurate measurement, the household case illustrates it, and the ending demands an account of the exclusion.")
reason(s, 1, "D", "level_confusion — Paragraph three names the rankings' administrative uses but expressly locates the complaint in what the index can represent, not merely in how officials use it.")
reason(s, 3, "C", "CORRECT — Paragraph three names agency as the absent object and subordinates the rankings' administrative uses to the question of what the index can represent.")
reason(s, 5, "B", "CORRECT — The claim turns on attributed agency altering conduct before any countable incident. If conduct changes only after such incidents, that proposed independent source of change is undermined; this does not make the index a complete record of agency.")
reason(s, 5, "C", "adjacent_answer — This changes the administrative use of the rankings, which paragraph three distinguishes from the index's inability to represent the relation itself.")
reason(s, 6, "D", "CORRECT — The analogy follows the concession that the colleague defends a real evidential standard. It explains how accurate inspection within a category can coexist with exclusion beyond that category, developing the opening problem.")
reason(s, 6, "C", "stage_misattribution — The next paragraph mentions administrative uses as subordinate consequences; the analogy explains limits of registration, not how rankings acquired authority.")

s = sets["0078"]
opt(s, 1, "B", "England's counts capture different objects; the records-based figure should lead because better practice can reduce its errors.")
s["questions"][3]["stem"] = "Which one of the following findings would most strengthen the author's claim that the records-based figure's errors are more fixable than the snapshot's?"
opt(s, 5, "A", "Councils doubled staff and eased applications but still missed the same share of qualifying households, who continued to avoid approaching.")
opt(s, 7, "C", "The snapshot gives an accurate count on the night it is taken, though that count soon becomes stale.")
opt(s, 7, "D", "The snapshot determines which households the council must assess as being owed a legal duty by morning.")
reason(s, 4, "B", "CORRECT — Improved intake reaches previously missing households, whereas additional looking adds little to the visible count. This supports the author's comparative claim about remediable access barriers.")
reason(s, 4, "D", "causal_inversion — A sharp response to additional counting effort would suggest a remediable snapshot error, weakening the contrast the author draws.")

s = sets["0080"]
opt(s, 1, "C", "What 1916 proved was a decree's control over published hours, rather than measured savings in fuel.")
opt(s, 1, "A", "The failure of farm hands and village clocks to comply rendered the national scheme unworkable.")
opt(s, 4, "B", "Railway timetables and published court hours remained unchanged for weeks after the Act took effect.")

s = sets["0081"]
s["tier"] = "hard"
opt(s, 2, "C", "New notes show the delegates settled that representation meant persons rather than communities before allocating seats.")
q = s["questions"][4]
q["stem"] = "What work does the tailor-and-coat comparison perform in the first paragraph?"
q["options"] = {
    "A": "To suggest that adapting an inherited political term leaves traces of the institutional assumptions for which it was originally designed.",
    "B": "To imply that a political vocabulary borrowed from corporate bodies cannot accommodate any later attempt to represent a people.",
    "C": "To show that the delegates' task was to restore representation's original meaning before choosing seats for the new legislature.",
    "D": "To indicate that later interpreters, rather than the delegates, created the mismatch between the word's corporate history and its new use.",
}
q["correct"] = "A"
q["reasons"] = {
    "A": "CORRECT — A tailor can refit the coat but cannot unmake its original cut: old darts remain visible. The comparison makes institutional inheritance a continuing constraint on the delegates' adaptation of the word.",
    "B": "scope_inflation — The coat can be refitted, and the delegates do adapt the term. Residual constraints do not make all later uses impossible.",
    "C": "stance_misread — The delegates fit inherited language to a new body; the metaphor describes adaptation under constraint, not a programme of restoring an original meaning.",
    "D": "stage_misattribution — The seams already show when the delegates use the term in 1787. Later interpreters recast the divided settlement; they do not originate this mismatch.",
}

s = sets["0082"]
trim(s, "Those of us who spent years explaining Strasbourg's reach by the antiquity of its Christkindelsmärik owe an answer to the obvious reply:", "Those of us who explained Strasbourg's reach by its Christkindelsmärik's antiquity must answer:")
trim(s, "The evidence is easy to lay out. ", "")
trim(s, "including coach parties from across Europe and beyond", "including coach parties from across Europe")
opt(s, 4, "A", "Rules for goods and booths will preserve the quay festival's character and eventually reshape commerce across the town.")
opt(s, 2, "A", "An official designation authorizing city-wide market status rather than confining the celebration to one square.")
reason(s, 1, "C", "CORRECT — The opening contrasts two old markets with different institutional outcomes; the licensing and routing discussion explains the closing claim that governance produced the divergence.")
reason(s, 3, "A", "CORRECT — The author reports having explained Strasbourg's reach by its market's antiquity, then concludes that age cannot explain why only one of two old traditions was authorized to expand.")

s = sets["0103"]
trim(s, "manufacturer employees authorized to sign off airframe compliance on the regulator's behalf, rating agencies paid by the issuers whose paper they grade, auditors appointed by the companies whose books they open, private certifiers engaged by the developer whose building they approve", "manufacturer employees signing off airframe compliance for regulators, rating agencies paid by issuers, auditors appointed by the companies they audit, certifiers engaged by developers")
trim(s, "the inspector drawing salary from another firm entirely", "the inspector salaried by another firm")
trim(s, "on the question of who pays is as clean an answer as the problem admits", "on who pays is as clean an answer as the problem admits")
trim(s, "Grant it properly. ", "")
trim(s, "The logic is sound as far as it goes. Press one case against it.", "Test that logic against one case.")
trim(s, "the accepted methods, the negotiated equivalencies, the history of why a particular analysis was allowed", "the accepted methods, negotiated equivalencies and reasons for allowing a particular analysis")
opt(s, 2, "B", "It addresses emotional closeness between inspector and client, which the author regards as the central problem in inspection.")
reason(s, 4, "D", "CORRECT — Paragraph four concedes that public employment settles who pays, then distinguishes budget, headcount and career pressures from private selection pressures. It therefore denies that a simple public takeover is the answer.")
q = s["questions"][7]
q["stem"] = "A pooled scheme assigns inspectors independently and sends their findings directly to the regulator. Manufacturers must disclose their records, but only their engineers can explain the accepted methods and negotiated equivalencies. Which assessment best follows from the passage?"
q["options"] = {
    "A": "Direct reporting makes the inspectors technically self-sufficient, although independent allocation may still produce poor matches between assignments and expertise.",
    "B": "The scheme removes client control of appointments, while reliance on the manufacturer's technical explanations can persist despite disclosure and direct reporting.",
    "C": "Dependence on client explanations means independent allocation leaves the manufacturer's power to select and reward favourable inspectors substantially intact.",
    "D": "The scheme's remaining dependence is a cost of short tenure that rotating teams more frequently should resolve without changing the allocation system.",
}
q["correct"] = "B"
q["reasons"] = {
    "A": "missing_link — Reporting routes determine where findings go, not where technical understanding resides. Paragraph three distinguishes possessing records from a usable grasp of accepted methods and equivalencies.",
    "B": "CORRECT — The final arrangement removes client selection and reward power, but paragraph three locates usable technical knowledge in the engineers. Disclosure and direct reporting do not themselves transfer that understanding.",
    "C": "level_confusion — Technical dependence and appointment control are different mechanisms. The scenario expressly removes the latter; dependence on explanations does not by itself restore selection or reward power.",
    "D": "causal_inversion — Rotation addresses familiarity but repeatedly requires newcomers to be taught by the inspected party. More frequent rotation therefore does not resolve the knowledge dependence described here.",
}

TARGETS = {
    "0093": "CDBABCAD", "0102": "CABDBCDA", "0077": "AACDCDBB", "0078": "BACDDCBA",
    "0080": "CCDBBDAA", "0081": "BCDDACBA", "0082": "CADCBBDA", "0103": "ACCDABDB",
}
GENRES = {
    "0093": "Art/design history — within brief.",
    "0102": "Law/public policy — genre exception retained by instruction.",
    "0077": "Anthropology with philosophical/epistemological argument — borderline; retained by instruction.",
    "0078": "Social policy/statistics — genre exception retained by instruction.",
    "0080": "Legislative/administrative history — genre exception retained by instruction.",
    "0081": "Political philosophy/intellectual history — defensible within brief.",
    "0082": "Urban/cultural governance — genre exception retained by instruction.",
    "0103": "Applied philosophy/institutional ethics — within brief.",
}


def render(s):
    text = f"RC ID: {s['id']} | Tier: {s['tier']} | Status: revised_candidate | Revised: 2026-09-19 (Asia/Calcutta)\n"
    text += "=" * 70 + "\n\n[PASSAGE]\n\n" + s["passage"] + "\n\n[QUESTIONS]\n\n"
    for q in s["questions"]:
        text += f"Q{q['n']}. {q['stem']}\n"
        text += "\n".join(f"({l}) {q['options'][l]}" for l in LETTERS) + "\n\n"
    text += "[ANSWER KEY & ELIMINATION LOGIC]\n\n"
    for q in s["questions"]:
        c = q["correct"]
        text += f"Q{q['n']} — Correct answer: ({c})\n"
        text += "\n".join(f"  ({l}) {q['reasons'][l]}" for l in [c] + [x for x in LETTERS if x != c]) + "\n\n"
    return text + s["source"].strip() + "\n"


def positions(lengths, key):
    v = lengths[key]
    if len(set(lengths.values())) == 1:
        return "all_equal"
    if v == max(lengths.values()):
        return "longest" if list(lengths.values()).count(v) == 1 else "tied_longest"
    if v == min(lengths.values()):
        return "shortest" if list(lengths.values()).count(v) == 1 else "tied_shortest"
    return "middle"


def audit(s):
    rows = []
    for q in s["questions"]:
        chars = {l: len(q["options"][l]) for l in LETTERS}
        words = {l: len(q["options"][l].split()) for l in LETTERS}
        rows.append(dict(question=q["n"], correct=q["correct"], characters=chars, words=words,
                         character_ratio=max(chars.values()) / min(chars.values()),
                         word_ratio=max(words.values()) / min(words.values()),
                         character_position=positions(chars, q["correct"]),
                         word_position=positions(words, q["correct"])))
    return dict(id=s["id"], tier=s["tier"], genre=GENRES[s["id"][-4:]],
                source_file=s["path"].relative_to(ROOT).as_posix(), original_sha256=s["original_sha256"],
                passage_words=len(s["passage"].split()),
                passage_lexical_words=len(re.findall(r"\b\w+(?:['’-]\w+)*\b", s["passage"])),
                key="".join(q["correct"] for q in s["questions"]),
                distribution=dict(sorted(Counter(q["correct"] for q in s["questions"]).items())), questions=rows)


OUT.mkdir(exist_ok=True)
audits = []
for short, s in sorted(sets.items()):
    for q, target in zip(s["questions"], TARGETS[short]):
        for l, val in q["options"].items():
            q["options"][l] = val[0].upper() + val[1:].rstrip(".") + "."
        old = q["correct"]
        mapping = {l: l for l in LETTERS}
        mapping[old], mapping[target] = target, old
        q["options"] = {mapping[l]: v for l, v in q["options"].items()}
        q["reasons"] = {mapping[l]: v for l, v in q["reasons"].items()}
        q["correct"] = target
        q["original_to_revised_letters"] = mapping
    text = render(s)
    destination = OUT / (s["id"] + ".txt")
    destination.write_text(text, encoding="utf-8", newline="\n")
    # Reparse what was actually written, rather than checking only in-memory data.
    readback = parse(destination)
    assert readback["passage"] == s["passage"]
    assert len(readback["questions"]) == 8
    for q in readback["questions"]:
        assert [l for l in LETTERS if q["reasons"][l].startswith("CORRECT —")] == [q["correct"]]
        assert all(v[0].isupper() and v.endswith(".") for v in q["options"].values())
    assert hashlib.sha256(s["path"].read_bytes()).hexdigest() == s["original_sha256"]
    a = audit(s)
    a["replaced_questions"] = {"0081": [5], "0103": [8]}.get(short, [])
    a["letter_maps"] = {str(q["n"]): q["original_to_revised_letters"] for q in s["questions"]
                        if q["n"] not in a["replaced_questions"]}
    a["revised_sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
    audits.append(a)

(OUT / "audit.json").write_text(json.dumps(audits, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
failures = []
for a in audits:
    chars = Counter(q["character_position"] for q in a["questions"])
    words = Counter(q["word_position"] for q in a["questions"])
    print(a["id"], a["tier"], a["passage_words"], a["passage_lexical_words"], a["key"], "chars", dict(chars), "words", dict(words))
    if not (500 <= a["passage_words"] <= 550 and 500 <= a["passage_lexical_words"] <= 550):
        failures.append(f"{a['id']}: passage length")
    if a["distribution"] != dict.fromkeys(LETTERS, 2):
        failures.append(f"{a['id']}: key distribution")
    if chars["longest"] + chars["tied_longest"] > 3 or chars["shortest"] + chars["tied_shortest"] > 3:
        failures.append(f"{a['id']}: character length tell")
    if words["longest"] > 3 or words["shortest"] > 3:
        failures.append(f"{a['id']}: word length tell")
    for q in a["questions"]:
        if q["character_ratio"] >= 1.30 or q["word_ratio"] >= 1.30:
            failures.append(f"{a['id']} Q{q['question']}: ratio chars={q['character_ratio']:.3f} words={q['word_ratio']:.3f}")
        print(" ", q["question"], q["correct"], list(q["characters"].values()), list(q["words"].values()), f"{q['character_ratio']:.3f}", q["character_position"])
print("FAILURES:", failures)
if failures:
    raise SystemExit(1)
