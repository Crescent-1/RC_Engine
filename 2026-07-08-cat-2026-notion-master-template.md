# 🎯 CAT 2026 — Master Command Center

> High-performance prep OS for a working professional. Zero fluff. Track → Analyze → Fix → Repeat.
>
> **Owner:** Ansh · **Target:** CAT 2026 · **Cadence:** Daily log → Weekly review → Mistake-book mastery

---

## ⚙️ How to build this in Notion (read once)

- Each `H1` (`#`) below = a **Notion page** or a **top section** on the dashboard.
- Each **"Database"** block = a Notion **inline or full-page database**. Create it with `/database`.
- The property tables under each database are the **exact columns** — create them in the order shown.
- `Property → Type` is written in `code blocks` so you can copy the schema at a glance.
- **Relations** connect the daily/weekly/mistake DBs so metrics roll up automatically.
- Anything in a `code block` labeled *Template* is meant to be pasted into a Notion **template button** or a synced block.

---

# 1. 🧭 Master Dashboard View

> This is your home page. Keep it to one screen. Everything else is one click deep.

## 1.1 Pre-Sprint Status Component

Build this as a **Callout block** (`/callout`) pinned to the top, or a 2-column layout of two callouts.

```
🔴 CURRENT PHASE — Pre-Sprint
   Window: July 8 – 16, 2026
   Goal: Rebuild core Quant + fix RC elimination habits
   Daily target: 3 hrs · Accuracy floor: 80%

🟡 NEXT PHASE — Maintenance Trip
   Window: July 17 – 25, 2026
   Goal: Hold gains, light revision, 1 sectional / 2 days
   Daily target: 1.5 hrs · No new topics
```

Layout suggestion (columns):

```
┌──────────────────────────┬──────────────────────────┐
│  🔴 CURRENT: Pre-Sprint  │  🟡 NEXT: Maintenance    │
│  Jul 8–16                │  Jul 17–25               │
│  ▸ Target 3 hrs/day      │  ▸ Target 1.5 hrs/day    │
│  ▸ Accuracy floor 80%    │  ▸ Revision only         │
└──────────────────────────┴──────────────────────────┘
```

**Phase tracker property (optional):** add a Select property `Phase` to the Daily Log with options
`Pre-Sprint`, `Maintenance Trip`, `Full Sprint`, `Mock Phase` so every day is tagged to a phase and you can filter the whole system by phase later.

## 1.2 Daily Check-In — Template Button

In Notion, create a **Template Button** (`/template button`) named **"➕ Daily Check-In"**. Configure it to add a new page/row to the **Daily Log Tracker** database and pre-fill the body with the block below. One click = today's log, ready to fill.

```
Template: Daily Check-In (paste into the button's template body)

## 📅 {{Today}} — Daily Check-In

**Phase:** Pre-Sprint
**Study Hours (target 3):**

### 🔢 Quant
- Lecture title:
- Qs solved:
- Accuracy %:
- One mistake logged? → [ ] Added to Mistake Book

### 📖 VARC
- RC passages:
- VA questions:
- One RC logged? → [ ] Added to RC Journal

### 🧩 DILR
- Sets solved:
- Solved independently? → [ ] Yes  [ ] Needed help
- One set logged? → [ ] Added to DILR Pattern Book

### 🔋 Wrap
- Energy level (1–10):
- Biggest learning today:
- Problems faced:
```

> **Pro tip:** In the Template Button config, set the date property to `Now` so `Date` auto-fills. Set the three "logged?" checkboxes as a daily forcing function — no day closes until one mistake is captured in each active section.

## 1.3 Dashboard linked views (put these below the callouts)

- **▸ This Week — Daily Log** → Linked view of *Daily Log Tracker*, filtered `Date is within the past 1 week`, sorted `Date ↓`.
- **▸ Needs Review** → Linked view of *Quant Mistake Book*, filtered `Revisit Status = Needs Review`.
- **▸ Weak Areas board** → Linked *Weekly Scorecard*, board grouped by `Identified Weak Areas`.
- **▸ Streak / Hours** → A `Sum` rollup of `Study Hours` shown at the bottom of the week view.

---

# 2. 🗓️ Database 1 — Daily Log Tracker

> The atomic unit. One row per day. Everything else aggregates from here.
> Create with `/database - full page`. Recommended default view: **Table**, sorted by `Date ↓`.

## 2.1 Properties

| Property | Type | Config / Notes |
|---|---|---|
| Date | Date | Primary sort. Set as title-adjacent; format `MMM DD`. |
| Study Hours | Number | Format `Number`, 1 decimal. |
| Quant: Lecture Title | Text | Free text. |
| Quant: Qs Solved | Number | Integer. |
| Quant: Accuracy % | Number | Format `Percent`. Enter as `0.82` = 82%. |
| VARC: RC Count | Number | Integer. |
| VARC: VA Count | Number | Integer. |
| DILR: Sets Solved | Number | Integer. |
| Energy Level | Select | Options `1`–`10` (color low=red → high=green). |
| Biggest Learning | Text | One line. |
| Problems Faced | Text | Feeds tomorrow's focus. |

```
Schema (copy order):
Date                 → Date
Study Hours          → Number (1 decimal)
Quant: Lecture Title → Text
Quant: Qs Solved     → Number
Quant: Accuracy %    → Number (Percent)
VARC: RC Count       → Number
VARC: VA Count       → Number
DILR: Sets Solved    → Number
Energy Level         → Select (1–10)
Biggest Learning     → Text
Problems Faced       → Text
```

## 2.2 Suggested extra properties (optional but powerful)

```
Phase        → Select (Pre-Sprint / Maintenance Trip / Full Sprint / Mock Phase)
Week         → Relation → Weekly Scorecard   (rolls daily rows into the week)
Mistakes ↗   → Relation → Quant Mistake Book (link mistakes logged that day)
```

## 2.3 Views to create

- **Table (default):** all columns, sorted `Date ↓`.
- **This Week:** filter `Date within past 1 week`. Footer rollups: `Sum(Study Hours)`, `Average(Quant: Accuracy %)`.
- **Calendar:** by `Date` — visual streak / gaps.
- **Low-Energy Flag:** filter `Energy Level ≤ 4` to spot burnout early.

---

# 3. 📊 Database 2 — Weekly Scorecard

> One row per week. Aggregates the daily log and holds qualitative weekly analysis.
> Create with `/database`. Title property = `Week` (e.g., `W1 · Jul 6–12`).

## 3.1 Properties

| Property | Type | Config / Notes |
|---|---|---|
| Week | Title | e.g., `W2 · Jul 13–19`. |
| Week Range | Date | Date range (start → end). |
| Daily Logs | Relation | → Daily Log Tracker (link that week's 7 rows). |
| Total Study Hours | Rollup | `Daily Logs · Study Hours · Sum`. |

### 🔢 Quant block

| Property | Type | Config / Notes |
|---|---|---|
| Quant: Topics Completed | Number | Manual count. |
| Quant: Total Questions | Rollup | `Daily Logs · Quant: Qs Solved · Sum`. |
| Quant: Avg Accuracy | Rollup | `Daily Logs · Quant: Accuracy % · Average`. |
| Quant: Weak Areas | Multi-select | Tag topics to attack next week. |

### 📖 VARC block

| Property | Type | Config / Notes |
|---|---|---|
| VARC: Total RC Count | Rollup | `Daily Logs · VARC: RC Count · Sum`. |
| VARC: Avg Accuracy | Number | Manual `Percent` (from RC Journal review). |
| VARC: Avg Solving Time | Number | Minutes/passage. |
| VARC: Trap Patterns | Text | Recurring wrong-option traps spotted. |

### 🧩 DILR block

| Property | Type | Config / Notes |
|---|---|---|
| DILR: Total Sets | Rollup | `Daily Logs · DILR: Sets Solved · Sum`. |
| DILR: Independent Solves | Number | Count solved with no help. |
| DILR: Avg Solving Time | Number | Minutes/set. |

### 🏁 Mocks block (future use)

| Property | Type | Config / Notes |
|---|---|---|
| Mock: Overall Percentile | Number | 1 decimal. |
| Mock: Sectional Percentiles | Text | `VARC / DILR / QA` e.g. `88 / 71 / 94`. |
| Mock: Major Lessons | Text | Top 3 takeaways. |
| Mock: Strategy Improvements | Text | Order of attempt, time allocation, skips. |

```
Schema (copy order):
Week                        → Title
Week Range                  → Date (range)
Daily Logs                  → Relation (Daily Log Tracker)
Total Study Hours           → Rollup (Sum)
Quant: Topics Completed     → Number
Quant: Total Questions      → Rollup (Sum)
Quant: Avg Accuracy         → Rollup (Average, Percent)
Quant: Weak Areas           → Multi-select
VARC: Total RC Count        → Rollup (Sum)
VARC: Avg Accuracy          → Number (Percent)
VARC: Avg Solving Time      → Number
VARC: Trap Patterns         → Text
DILR: Total Sets            → Rollup (Sum)
DILR: Independent Solves    → Number
DILR: Avg Solving Time      → Number
Mock: Overall Percentile    → Number
Mock: Sectional Percentiles → Text
Mock: Major Lessons         → Text
Mock: Strategy Improvements → Text
```

## 3.2 Weekly review layout (inside each week's page body)

```
## Week X Review
1. Numbers vs target →  Hours: __ / 21   Quant Acc: __%   RC done: __
2. What worked
3. What leaked (time / accuracy / stamina)
4. Weak areas → carried into next week's Quant plan
5. One process change for next week
```

---

# 4. ❌ Database 3 — The Quant Mistake Book

> Every wrong/slow Quant question becomes an entry. This is the highest-ROI database in the system.
> Default view: **Board grouped by `Core Reason for Mistake`** — patterns jump out instantly.

## 4.1 Properties

| Property | Type | Config / Notes |
|---|---|---|
| Problem | Title | Short label / question stem. |
| Date Added | Date | Default `Now`. |
| Concept / Topic | Multi-select | e.g., `Number System`, `TSD`, `P&C`, `Geometry`, `Algebra`. |
| Core Reason for Mistake | Select | `Concept Gap` · `Calculation Error` · `Time Pressure` · `Misread Question`. |
| Shortcut / Correct Method | Text | The clean method to internalize. |
| Revisit Status | Select | `Needs Review` · `Retested & Mastered`. |

```
Schema (copy order):
Problem                    → Title
Date Added                 → Date (default: Now)
Concept / Topic            → Multi-select (Tags)
Core Reason for Mistake    → Select: Concept Gap | Calculation Error | Time Pressure | Misread Question
Shortcut / Correct Method  → Text
Revisit Status             → Select: Needs Review | Retested & Mastered
```

## 4.2 Views to create

- **Board by Reason (default):** group by `Core Reason for Mistake`. Instantly see if you're losing points to concepts vs calculation vs reading.
- **Needs Review:** filter `Revisit Status = Needs Review`, sort `Date Added ↑` (oldest first — clear the backlog).
- **By Topic:** board grouped by `Concept / Topic` → find your leakiest chapter.
- **Mastery log:** filter `Retested & Mastered` → proof of progress.

> **Rule:** an entry only moves to `Retested & Mastered` after you re-solve it cold on a later day. No shortcuts.

---

# 5. 📖 Database 4 — The RC Journal

> One row per RC passage attempted. Turns reading into a diagnosable skill.
> Default view: **Table**, sorted `Date ↓`. Secondary: **Board by `Specific Reason for Error`**.

## 5.1 Properties

| Property | Type | Config / Notes |
|---|---|---|
| Passage | Title | Short handle. |
| Date | Date | Default `Now`. |
| Passage Topic / Source | Text | e.g., `Philosophy — Aeon`, `Economics — mock RC-3`. |
| Main Idea Summary | Text | Force yourself to write it in 1–2 lines. |
| Questions Missed | Number | Integer. |
| Specific Reason for Error | Select | `Flawed Elimination` · `Tone Misinterpretation` · `Over-generalized Option` · `Misread Detail`. |

```
Schema (copy order):
Passage                   → Title
Date                      → Date (default: Now)
Passage Topic / Source    → Text
Main Idea Summary         → Text
Questions Missed          → Number
Specific Reason for Error → Select: Flawed Elimination | Tone Misinterpretation | Over-generalized Option | Misread Detail
```

## 5.2 Views to create

- **Table (default):** sorted `Date ↓`.
- **Error-pattern board:** group by `Specific Reason for Error` → see whether elimination or tone is your #1 leak.
- **High-miss filter:** `Questions Missed ≥ 2` → the passages worth re-reading.

> **Analysis habit:** at week's end, count entries per reason and copy the top pattern into `Weekly Scorecard → VARC: Trap Patterns`.

---

# 6. 🧩 Database 5 — The DILR Pattern Book

> One row per set. Builds a personal library of "crack points" for set types.
> Default view: **Board grouped by `Set Name / Type`**.

## 6.1 Properties

| Property | Type | Config / Notes |
|---|---|---|
| Set | Title | Short handle / source. |
| Date | Date | Default `Now`. |
| Set Name / Type | Select | `Arrangement` · `Matrix` · `Games & Tournaments` · `Graphs` · `Venn/Sets` · `Sequencing` · `Data Sufficiency`. |
| Key Insight / Crack Point | Text | The one observation that unlocked it. |
| Friction Point | Text | Where exactly you got stuck. |
| Solved Independently? | Checkbox | ✅ = no help. |

```
Schema (copy order):
Set                        → Title
Date                       → Date (default: Now)
Set Name / Type            → Select: Arrangement | Matrix | Games & Tournaments | Graphs | Venn/Sets | Sequencing | Data Sufficiency
Key Insight / Crack Point  → Text
Friction Point             → Text
Solved Independently?      → Checkbox
```

## 6.2 Views to create

- **Board by Type (default):** group by `Set Name / Type` → which set type do you attempt most / least?
- **Not-yet-independent:** filter `Solved Independently? = unchecked` → your practice queue.
- **Crack-point library:** gallery/table showing `Set Name / Type` + `Key Insight` → skim before a mock.

---

# 7. 🔗 Relation & rollup map (wire these once)

```
Daily Log Tracker ──(Week)──▶ Weekly Scorecard
      │                            ▲
      │                            └── rollups: Sum(Study Hours),
      │                                Sum(Quant Qs), Avg(Quant Acc),
      │                                Sum(RC Count), Sum(DILR Sets)
      │
      └──(Mistakes ↗)──▶ Quant Mistake Book   (link each day's mistakes)

RC Journal ─────────▶ (weekly manual roll-up) ─▶ Weekly Scorecard: Trap Patterns
DILR Pattern Book ──▶ (weekly manual roll-up) ─▶ Weekly Scorecard: DILR fields
```

# 8. ✅ Daily / Weekly operating rhythm

```
DAILY  (5 min close-out)
  1. Click ➕ Daily Check-In → fill numbers
  2. Log ≥1 Quant mistake, ≥1 RC, ≥1 DILR set
  3. Rate energy · note biggest learning + problem faced

WEEKLY (30 min, Sunday)
  1. Create Weekly Scorecard row → link the 7 daily logs
  2. Read rollups: hours, accuracy, counts vs target
  3. Count Mistake Book by reason → set next week's Quant focus
  4. Copy top RC trap + DILR weak type into scorecard
  5. Write the 5-line Week Review
```

---

*End of blueprint. Section numbers map 1:1 to your request; databases are relation-wired so weekly metrics aggregate automatically.*
