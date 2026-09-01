"""Regenerates RC_Tracker.xlsx from rc_pipeline.db. Re-run any time to refresh.
Manual columns on the 'RC Sets' sheet (Shared to Institute / Shared On /
Remarks) are preserved across rebuilds, matched by RC_ID."""
import json, os, sqlite3, sys

# Derived, never hardcoded: this line has twice been left pointing at a
# directory the project had already moved away from.
PROJ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJ)
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

OUT = os.path.join(PROJ, "RC_Tracker.xlsx")

# manual columns to carry over (header text -> value per RC_ID)
MANUAL_HEADERS = ["Shared to Institute (Y/N)", "Shared On", "Remarks"]


def read_manual_entries(path):
    """RC_ID -> {header: value} from an existing tracker, tolerant of the
    user reordering columns (matched by header text, not position)."""
    if not os.path.exists(path):
        return {}
    try:
        old = load_workbook(path, data_only=False)["RC Sets"]
    except Exception:
        return {}
    headers = {c.value: c.column for c in old[1] if c.value}
    if "RC_ID" not in headers:
        return {}
    cols = {h: headers[h] for h in MANUAL_HEADERS if h in headers}
    out = {}
    for r in range(2, old.max_row + 1):
        rc_id = old.cell(row=r, column=headers["RC_ID"]).value
        if not rc_id:
            continue
        vals = {h: old.cell(row=r, column=c).value for h, c in cols.items()}
        if any(v not in (None, "") for v in vals.values()):
            out[rc_id] = vals
    return out


manual = read_manual_entries(OUT)

conn = sqlite3.connect(PROJ + r"\rc_pipeline.db")
cur = conn.cursor()

fam_names = {f["id"]: f["name"] for f in
             json.load(open(PROJ + r"\rc_engine\components\families.json",
                            encoding="utf-8"))["items"]}
fam_postures = {f["id"]: f["closing_posture"] for f in
                json.load(open(PROJ + r"\rc_engine\components\families.json",
                               encoding="utf-8"))["items"]}

# shipped sets
cur.execute("""SELECT r.rc_id, r.tier, r.status, r.average_score, r.compliance_f1,
                      r.novelty_composite, r.total_cost_usd, r.created_at,
                      b.family_id, r.domain
               FROM rc_sets r LEFT JOIN blueprints b ON b.blueprint_id = r.blueprint_id
               ORDER BY r.created_at""")
rc_rows = cur.fetchall()

# realized postures from fingerprints
postures = {}
for rc_id, sty in cur.execute("SELECT rc_id, stylometry FROM fingerprints"):
    d = json.loads(sty)
    if d.get("_closing_posture"):
        postures[rc_id] = d["_closing_posture"]

# failed blueprints (never shipped) with rejection reason
cur.execute("""SELECT b.blueprint_id, b.tier, b.family_id, b.status, b.created_at,
                      (SELECT details FROM novelty_audits n
                       WHERE n.blueprint_id = b.blueprint_id
                       ORDER BY n.created_at DESC LIMIT 1)
               FROM blueprints b WHERE b.status != 'shipped'
               ORDER BY b.created_at""")
fail_rows = cur.fetchall()
conn.close()

HDR_FILL = PatternFill("solid", start_color="1F4E78")
HDR_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=10)
BODY = Font(name="Arial", size=10)
STATUS_FILL = {"approved": PatternFill("solid", start_color="C6EFCE"),
               "needs_review": PatternFill("solid", start_color="FFEB9C"),
               "solver_dispute": PatternFill("solid", start_color="FFC7CE")}

wb = Workbook()

# ---------------------------------------------------------------- RC Sets
ws = wb.active
ws.title = "RC Sets"
headers = ["RC_ID", "Tier", "Status", "Judge Score", "Compliance F1", "Novelty",
           "Cost ($)", "Generated On", "Family", "Closing Posture", "Topic",
           "Shared to Institute (Y/N)", "Shared On", "Remarks"]
ws.append(headers)
carried = 0
for r in rc_rows:
    rc_id, tier, status, avg, f1, nov, cost, created, fam, domain = r
    fam_disp = f"{fam} {fam_names.get(fam, '')}".strip() if fam else ""
    posture = postures.get(rc_id) or fam_postures.get(fam, "") or ""
    kept = manual.get(rc_id, {})
    if kept:
        carried += 1
    ws.append([rc_id, tier, status, avg, f1, nov, cost,
               (created or "")[:10], fam_disp, posture, domain or "",
               kept.get(MANUAL_HEADERS[0], ""), kept.get(MANUAL_HEADERS[1], ""),
               kept.get(MANUAL_HEADERS[2], "")])
n = len(rc_rows) + 1
for c in range(1, len(headers) + 1):
    cell = ws.cell(row=1, column=c)
    cell.fill, cell.font = HDR_FILL, HDR_FONT
    cell.alignment = Alignment(horizontal="center", wrap_text=True)
for row in ws.iter_rows(min_row=2, max_row=n):
    for cell in row:
        cell.font = BODY
    st = row[2].value
    if st in STATUS_FILL:
        row[2].fill = STATUS_FILL[st]
for col, w in zip("ABCDEFGHIJKLMN",
                  [24, 8, 14, 11, 13, 9, 9, 12, 30, 20, 34, 20, 11, 28]):
    ws.column_dimensions[col].width = w
for row in ws.iter_rows(min_row=2, max_row=n, min_col=4, max_col=7):
    for cell in row:
        cell.number_format = "0.00"
ws.freeze_panes = "A2"
ws.auto_filter.ref = f"A1:N{n}"

# ---------------------------------------------------------- Failed Attempts
wf = wb.create_sheet("Failed Attempts")
fheaders = ["Blueprint ID", "Tier", "Family", "Status", "Date",
            "Rejection Reason (novelty audit)"]
wf.append(fheaders)
for bp_id, tier, fam, status, created, details in fail_rows:
    fam_disp = f"{fam} {fam_names.get(fam, '')}".strip() if fam else ""
    wf.append([bp_id, tier, fam_disp, status, (created or "")[:10], details or ""])
for c in range(1, len(fheaders) + 1):
    cell = wf.cell(row=1, column=c)
    cell.fill, cell.font = HDR_FILL, HDR_FONT
    cell.alignment = Alignment(horizontal="center", wrap_text=True)
for row in wf.iter_rows(min_row=2, max_row=len(fail_rows) + 1):
    for cell in row:
        cell.font = BODY
for col, w in zip("ABCDEF", [22, 8, 28, 18, 12, 70]):
    wf.column_dimensions[col].width = w
wf.freeze_panes = "A2"
wf.auto_filter.ref = f"A1:F{len(fail_rows) + 1}"

# ----------------------------------------------------------------- Summary
wsum = wb.create_sheet("Summary")
wsum["A1"] = "RC Generation Summary"
wsum["A1"].font = Font(name="Arial", bold=True, size=13)
rows = [
    ("Total shipped RC sets", f"=COUNTA('RC Sets'!A2:A{max(n,2)})"),
    ("Approved", "=COUNTIF('RC Sets'!C:C,\"approved\")"),
    ("Needs review", "=COUNTIF('RC Sets'!C:C,\"needs_review\")"),
    ("Solver dispute", "=COUNTIF('RC Sets'!C:C,\"solver_dispute\")"),
    ("Failed attempts (never shipped)",
     f"=COUNTA('Failed Attempts'!A2:A{max(len(fail_rows)+1,2)})"),
    ("", ""),
    ("Elite shipped", "=COUNTIF('RC Sets'!B:B,\"elite\")"),
    ("Hard shipped", "=COUNTIF('RC Sets'!B:B,\"hard\")"),
    ("Medium shipped", "=COUNTIF('RC Sets'!B:B,\"medium\")"),
    ("", ""),
    ("Total generation cost ($)", "=SUM('RC Sets'!G:G)"),
    ("Shared to institute",
     "=COUNTIF('RC Sets'!L:L,\"Y\")+COUNTIF('RC Sets'!L:L,\"y\")+COUNTIF('RC Sets'!L:L,\"Yes\")"),
]
for i, (label, formula) in enumerate(rows, start=3):
    wsum.cell(row=i, column=1, value=label).font = BODY
    if formula:
        c = wsum.cell(row=i, column=2, value=formula)
        c.font = Font(name="Arial", size=10, bold=True)
wsum.cell(row=13, column=2).number_format = "0.0000"
wsum.column_dimensions["A"].width = 32
wsum.column_dimensions["B"].width = 14

wb.save(OUT)
print(f"Saved {OUT}: {len(rc_rows)} shipped, {len(fail_rows)} failed attempts, "
      f"{carried} manual entr{'y' if carried == 1 else 'ies'} preserved")
dropped = set(manual) - {r[0] for r in rc_rows}
if dropped:
    print(f"WARNING: manual entries for RC_IDs no longer in the DB were dropped: "
          f"{sorted(dropped)}")
