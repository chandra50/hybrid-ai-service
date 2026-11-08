"""Build docs/hybrid-ai-design.pptx from the content of docs/DESIGN.md.

    pip install python-pptx
    python tools/build_deck.py [output.pptx]

Uses python-pptx only. All text is Arial so it renders the same in
PowerPoint and LibreOffice.
"""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

# ---------------------------------------------------------------- palette
INK = "14232B"        # deep slate - dark slides
SLATE = "2E4756"
TEAL = "1B8A8F"
AMBER = "F2A900"      # safety amber - the accent
TEXT = "1E2A30"
MUTED = "5B6B73"
TINT = "EEF3F4"       # card tint on white slides
TINT2 = "E3ECEE"
WHITE = "FFFFFF"
ON_DARK = "C9D6DB"
ON_DARK_MUTED = "93A7B0"

MODE = {  # status colors for operating modes (fill, text)
    "M0": ("2E8B57", WHITE), "M1": ("9BBF3B", TEXT), "M2": ("F2C230", TEXT),
    "M3": ("7A5AA6", WHITE), "M4": ("D9732B", WHITE), "M5": ("B83227", WHITE),
    "M6": ("5B6B73", WHITE),
}
MODE_NAME = {
    "M0": "Connected", "M1": "Constrained", "M2": "Intermittent", "M3": "Cloud AI down",
    "M4": "Hub island", "M5": "Fully offline", "M6": "Sensors lost",
}
TIER = {  # fill, text
    "Cloud": (SLATE, WHITE), "Hub": (TEAL, WHITE), "Field": ("3E9E77", WHITE), "Edge": (AMBER, TEXT),
}

FONT = "Arial"
MONO = "Courier New"
W, H = 13.333, 7.5
MX = 0.6  # side margin
CW = W - 2 * MX  # content width


def rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h)


# ---------------------------------------------------------------- helpers
class Deck:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(W), Inches(H)
        self.layout = self.prs.slide_layouts[5]  # Title Only
        self.n = 0

    def slide(self, title: str, dark: bool = False, notes: str = "", title_size: int = 36,
              title_box=(MX, 0.45, CW, 0.9)):
        s = self.prs.slides.add_slide(self.layout)
        self.n += 1
        bg = s.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb(INK if dark else WHITE)
        t = s.shapes.title
        t.left, t.top, t.width, t.height = (Inches(v) for v in title_box)
        tf = t.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = 0
        tf.vertical_anchor = MSO_ANCHOR.TOP
        tf.text = title
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT
        for r in p.runs:
            r.font.name, r.font.size, r.font.bold = FONT, Pt(title_size), True
            r.font.color.rgb = rgb(WHITE if dark else TEXT)
        if notes:
            s.notes_slide.notes_text_frame.text = notes
        if not dark or self.n > 1:
            self.text(s, W - MX - 1.0, H - 0.45, 1.0, 0.3, str(self.n), size=10,
                      color=ON_DARK_MUTED if dark else MUTED, align=PP_ALIGN.RIGHT)
        return s

    # text ---------------------------------------------------------------
    @staticmethod
    def _style_run(r, size, color, bold=False, italic=False, font=FONT):
        r.font.name, r.font.size, r.font.bold, r.font.italic = font, Pt(size), bold, italic
        r.font.color.rgb = rgb(color)

    def _fill_tf(self, tf, paras, size, color, bold, italic, align, font, space_after, bullet):
        if isinstance(paras, str):
            paras = [paras]
        for i, spec in enumerate(paras):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align
            if space_after:
                p.space_after = Pt(space_after)
            opts = {}
            if isinstance(spec, dict):
                opts = spec
                runs = spec.get("runs") or [(spec["text"], {})]
            elif isinstance(spec, tuple):
                runs = [spec]
            else:
                runs = [(spec, {})]
            for text, ro in runs:
                r = p.add_run()
                r.text = text
                self._style_run(r, ro.get("size", opts.get("size", size)), ro.get("color", opts.get("color", color)),
                                ro.get("bold", opts.get("bold", bold)), ro.get("italic", opts.get("italic", italic)),
                                ro.get("font", opts.get("font", font)))
            if opts.get("bullet", bullet):
                pPr = p._p.get_or_add_pPr()
                pPr.set("marL", str(int(Inches(0.25))))
                pPr.set("indent", str(int(-Inches(0.25))))
                bu = etree.SubElement(pPr, qn("a:buChar"))
                bu.set("char", "•")

    def text(self, s, x, y, w, h, paras, size=16, color=TEXT, bold=False, italic=False,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, font=FONT, space_after=0, bullet=False, margin=0.0):
        tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Inches(margin)
        self._fill_tf(tf, paras, size, color, bold, italic, align, font, space_after, bullet)
        return tb

    # shapes -------------------------------------------------------------
    def box(self, s, x, y, w, h, fill=TINT, paras=None, size=16, color=TEXT, bold=False,
            align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, radius=0.08, line=None, dash=False,
            margin=0.18, shape=MSO_SHAPE.ROUNDED_RECTANGLE, font=FONT, space_after=0, italic=False):
        sh = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
        if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
            sh.adjustments[0] = radius
        if fill is None:
            sh.fill.background()
        else:
            sh.fill.solid()
            sh.fill.fore_color.rgb = rgb(fill)
        if line:
            sh.line.color.rgb = rgb(line)
            sh.line.width = Pt(1.5)
            if dash:
                ln = sh.line._get_or_add_ln()
                d = etree.SubElement(ln, qn("a:prstDash"))
                d.set("val", "dash")
        else:
            sh.line.fill.background()
        sh.shadow.inherit = False
        tf = sh.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = Inches(margin)
        tf.margin_top = tf.margin_bottom = Inches(min(margin, 0.12))
        if paras is not None:
            self._fill_tf(tf, paras, size, color, bold, italic, align, font, space_after, False)
        return sh

    def badge(self, s, cx, cy, d, label, fill=AMBER, color=TEXT, size=16, bold=True):
        return self.box(s, cx - d / 2, cy - d / 2, d, d, fill=fill, paras=label, size=size, color=color,
                        bold=bold, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, shape=MSO_SHAPE.OVAL,
                        margin=0.02)

    def chip(self, s, x, y, w, h, label, fill, color, size=12, bold=True):
        return self.box(s, x, y, w, h, fill=fill, paras=label, size=size, color=color, bold=bold,
                        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, radius=0.5, margin=0.04)

    def arrow(self, s, x1, y1, x2, y2, color=MUTED, width=2.0, dash=False, both=False):
        c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        c.line.color.rgb = rgb(color)
        c.line.width = Pt(width)
        ln = c.line._get_or_add_ln()
        if dash:
            etree.SubElement(ln, qn("a:prstDash")).set("val", "dash")
        if both:
            etree.SubElement(ln, qn("a:headEnd")).set("type", "triangle")
        etree.SubElement(ln, qn("a:tailEnd")).set("type", "triangle")
        return c

    def line(self, s, x1, y1, x2, y2, color=TINT2, width=3.0):
        c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        c.line.color.rgb = rgb(color)
        c.line.width = Pt(width)
        return c

    def table(self, s, x, y, col_w, rows, row_h=0.6, header_fill=SLATE, size=14, first_col_fills=None,
              header_size=14):
        nrows, ncols = len(rows), len(col_w)
        gt = s.shapes.add_table(nrows, ncols, Inches(x), Inches(y), Inches(sum(col_w)), Inches(row_h * nrows))
        tbl = gt.table
        tblPr = tbl._tbl.tblPr
        for a in ("firstRow", "bandRow"):
            tblPr.set(a, "0")
        for j, cw in enumerate(col_w):
            tbl.columns[j].width = Inches(cw)
        for i, row in enumerate(rows):
            tbl.rows[i].height = Inches(row_h)
            for j, val in enumerate(row):
                cell = tbl.cell(i, j)
                cell.margin_left = cell.margin_right = Inches(0.1)
                cell.margin_top = cell.margin_bottom = Inches(0.05)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                fill, color, bold = (TINT if i % 2 else WHITE), TEXT, False
                if i == 0:
                    fill, color, bold = header_fill, WHITE, True
                elif j == 0 and first_col_fills:
                    fill, color = first_col_fills[i - 1]
                    bold = True
                elif j == 0:
                    bold = True
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb(fill)
                tf = cell.text_frame
                tf.word_wrap = True
                spec = val if isinstance(val, (list, dict)) else [val]
                self._fill_tf(tf, spec, header_size if i == 0 else size, color, bold, False,
                              PP_ALIGN.LEFT, FONT, 0, False)
        return gt

    def save(self, path):
        self.prs.save(path)


# ---------------------------------------------------------------- slides
def build(out: Path) -> None:
    d = Deck()
    C = PP_ALIGN.CENTER
    MID = MSO_ANCHOR.MIDDLE

    # 1 - Title ---------------------------------------------------------
    s = d.slide("hybrid-ai", dark=True, title_size=60, title_box=(0.8, 1.7, 7.6, 1.1),
                notes="hybrid-ai is a design for MCP-based agents that help maintain a California "
                      "industrial equipment fleet, built to keep working when connectivity or the cloud fails.")
    d.text(s, 0.8, 2.95, 7.4, 1.3, "Field-service agents that keep working when the network doesn't",
           size=28, color=ON_DARK)
    d.text(s, 0.8, 4.6, 7.4, 0.9, ["MCP agent design for a California industrial fleet",
                                   "Design v0.2  ·  November 2026"], size=16, color=ON_DARK_MUTED, space_after=4)
    tiers = [("Cloud", "T3"), ("Hub", "T2"), ("Field", "T1"), ("Edge", "T0")]
    for i, (name, code) in enumerate(tiers):
        fill, col = TIER[name]
        y = 1.55 + i * 1.15
        d.box(s, 9.3, y, 3.2, 0.8, fill=fill, paras=[{"runs": [(f"{code}  ", {"bold": True}), (name, {})]}],
              size=20, color=col, anchor=MID, align=C, radius=0.3)
        if i < 3:
            d.arrow(s, 10.9, y + 0.82, 10.9, y + 1.13, color=ON_DARK_MUTED, width=1.5, dash=True, both=True)

    # 2 - Problem -------------------------------------------------------
    s = d.slide("Six decisions behind every equipment issue",
                notes="Every issue runs the same chain from W1 to W6. The constraints at the bottom are what "
                      "make a cloud-only design fail in rural California.")
    flows = [("W1", "Triage", "What is wrong, how bad, safe to run?"),
             ("W2", "Technician", "Who is qualified, close and available?"),
             ("W3", "Location", "Fix on site or pull to a workshop?"),
             ("W4", "Parts", "Van, depot, warehouse or order? Reserve them"),
             ("W5", "Execution", "Procedures, manuals, LOTO at the asset"),
             ("W6", "Close-out", "Record the fix so triage gets smarter")]
    cw, gap = 1.85, 0.2
    for i, (code, name, q) in enumerate(flows):
        x = MX + i * (cw + gap)
        d.box(s, x, 1.65, cw, 2.55, fill=TINT)
        d.badge(s, x + cw / 2, 2.15, 0.62, code, fill=AMBER, size=14)
        d.text(s, x + 0.12, 2.6, cw - 0.24, 0.4, name, size=17, bold=True, align=C)
        d.text(s, x + 0.12, 3.05, cw - 0.24, 1.1, q, size=14, color=MUTED, align=C)
    d.text(s, MX, 4.55, CW, 0.4, "What makes it hard here", size=20, bold=True)
    cons = [("Connectivity gaps", "Valley, desert and foothill dead zones; wildfire power shutoffs (PSPS) for days"),
            ("Heavy live data", "Vibration, pressure, PLC alarms can't all stream raw over weak links"),
            ("Heavy knowledge", "Manuals and years of repair history are gigabytes, not on-demand fetches"),
            ("Safety and cost", "People approve dispatch, shutdowns and parts; no acting on stale data")]
    cw4 = (CW - 3 * 0.3) / 4
    for i, (h, b) in enumerate(cons):
        x = MX + i * (cw4 + 0.3)
        d.box(s, x, 5.05, cw4, 1.8, fill=WHITE, line=TINT2,
              paras=[{"text": h, "bold": True, "size": 16}, {"text": b, "size": 14, "color": MUTED}], space_after=4)

    # 3 - Design goal -----------------------------------------------------
    s = d.slide("Design goal", dark=True, title_size=20, title_box=(0.8, 0.8, 6, 0.5),
                notes="This is the one idea everything else hangs on.")
    s.shapes.title.text_frame.paragraphs[0].runs[0].font.color.rgb = rgb(AMBER)
    d.text(s, 0.8, 1.45, 11.7, 1.9,
           "Every workflow has a cloud-best answer and a local good-enough answer, behind the same interface",
           size=32, bold=True, color=WHITE)
    pillars = [("1", "One MCP contract at every tier", "Same tool names and schemas at edge, field, hub and cloud"),
               ("2", "A router picks who answers", "Per call, based on the current connectivity mode and deadlines"),
               ("3", "Every answer says how fresh it is", "Source tier, as-of time, staleness, provisional or confirmed")]
    pw = (11.7 - 2 * 0.4) / 3
    for i, (n, h, b) in enumerate(pillars):
        x = 0.8 + i * (pw + 0.4)
        d.badge(s, x + 0.35, 4.25, 0.7, n, fill=AMBER, size=20)
        d.text(s, x, 4.8, pw, 0.85, h, size=20, bold=True, color=WHITE)
        d.text(s, x, 5.7, pw, 1.0, b, size=16, color=ON_DARK)

    # 4 - Architecture ----------------------------------------------------
    s = d.slide("Four tiers, each able to stand alone",
                notes="Tiers degrade independently. Each one is authoritative for something, which is what makes "
                      "conflict handling simple later.")
    rows = [("Cloud", "T3  Cloud", "Claude orchestrator · CMMS, ERP, full manuals and repair history, fleet analytics",
             "Work orders, assignments, reservations, purchase orders"),
            ("Hub", "T2  Regional depot hub", "Mid-size local model · regional mirror of manuals, history, roster, depot stock",
             "Depot stock and workshop bays"),
            ("Field", "T1  Technician device", "Small on-device model · mission packs, van stock, offline outbox",
             "Van stock and on-site observations"),
            ("Edge", "T0  Site edge gateway", "No LLM: rules and anomaly models · live telemetry, 7–30 day buffer",
             "Live equipment state and alarms")]
    d.text(s, 7.35, 1.45, 5.3, 0.35, "AUTHORITATIVE FOR", size=12, bold=True, color=MUTED)
    for i, (tier, name, desc, auth) in enumerate(rows):
        y = 1.85 + i * 1.3
        fill, col = TIER[tier]
        d.box(s, MX, y, 6.35, 1.05, fill=fill,
              paras=[{"text": name, "bold": True, "size": 18}, {"text": desc, "size": 14}], color=col, anchor=MID)
        d.text(s, 7.35, y, 5.35, 1.05, auth, size=16, anchor=MID)
        if i < 3:
            d.arrow(s, MX + 3.2, y + 1.07, MX + 3.2, y + 1.28, color=MUTED, width=1.5, dash=True, both=True)

    # 5 - Contract --------------------------------------------------------
    s = d.slide("One MCP contract, many implementations",
                notes="Agents never know which tier answered unless they read the provenance fields, and they "
                      "are instructed to tell the technician whenever data is provisional or stale.")
    tools = ["diagnose_issue", "find_technicians", "recommend_repair_location", "check_parts",
             "reserve_parts", "search_knowledge", "get_live_telemetry", "update_work_order"]
    d.text(s, MX, 1.5, 6.0, 0.4, "8 tools, same JSON Schemas at every tier", size=18, bold=True)
    for i, t in enumerate(tools):
        col, row = i % 2, i // 2
        d.box(s, MX + col * 3.05, 2.05 + row * 0.75, 2.9, 0.6, fill=TINT, paras=t, size=12, font=MONO,
              anchor=MID, bold=True, margin=0.12)
    d.text(s, MX, 5.15, 5.95, 1.3, "Only the data behind them changes: depth and freshness. Swapping a backend "
           "(for example a real CMMS later) never changes the agents.", size=14, color=MUTED)
    d.text(s, 7.15, 1.5, 5.55, 0.4, "Every response carries provenance", size=18, bold=True)
    code = ['{', '  "result": { … },', '  "source_tier": "field",', '  "as_of": "2026-11-08T14:02Z",',
            '  "staleness_s": 18240,', '  "confidence": "provisional",', '  "authoritative": false', '}']
    d.box(s, 7.15, 2.05, 5.55, 3.35, fill=INK, paras=code, font=MONO, size=15, color=ON_DARK, margin=0.3,
          anchor=MID)
    d.text(s, 7.15, 5.6, 5.55, 0.9, '"Roster is 5 h old, so this assignment is provisional until sync."',
           size=15, italic=True, color=TEAL)

    # 6 - Router ----------------------------------------------------------
    s = d.slide("The router decides who answers each call",
                notes="The router is a small local service on every node. Agents connect to it as their only MCP "
                      "endpoint, which keeps the agents simple.")
    steps = [("Check mode", "Current mode and health of each tier"),
             ("Try tiers in order", "Policy order per tool"),
             ("Enforce a deadline", "For example 3 s on a slow link, then fall back"),
             ("Queue writes", "Unreachable owner: write goes to the outbox"),
             ("Label the answer", "Attach provenance before returning")]
    sw, sg = 2.06, 0.45
    for i, (h, b) in enumerate(steps):
        x = MX + i * (sw + sg)
        d.badge(s, x + sw / 2, 2.05, 0.75, str(i + 1), fill=AMBER, size=20)
        d.text(s, x, 2.6, sw, 0.5, h, size=17, bold=True, align=C)
        d.text(s, x, 3.1, sw, 1.0, b, size=14, color=MUTED, align=C)
        if i < 4:
            d.arrow(s, x + sw / 2 + 0.45, 2.05, x + sw + sg + sw / 2 - 0.45, 2.05, color=MUTED, width=2)
    d.text(s, MX, 4.55, CW, 0.4, "Example policies", size=18, bold=True)
    pol = [("find_technicians", ["Cloud", "Hub", "Field"]), ("get_live_telemetry", ["Edge", "Cloud"]),
           ("reserve_parts", ["Cloud", "Hub", "Field"])]
    for i, (tool, order) in enumerate(pol):
        y = 5.1 + i * 0.6
        d.text(s, MX, y, 3.4, 0.45, tool, size=15, font=MONO, bold=True, anchor=MID)
        for j, t in enumerate(order):
            x = 4.2 + j * 1.9
            fill, col = TIER[t]
            d.chip(s, x, y + 0.02, 1.4, 0.42, t, fill, col, size=13)
            if j < len(order) - 1:
                d.arrow(s, x + 1.45, y + 0.23, x + 1.85, y + 0.23, color=MUTED, width=1.5)
    d.text(s, 9.9, 5.1, 2.8, 1.6, "Writes from Hub or Field come back as soft or provisional",
           size=14, color=MUTED, italic=True)

    # 7 - Agents ----------------------------------------------------------
    s = d.slide("Specialist agents, coordinated by an orchestrator",
                notes="Offline, the field assistant runs a reduced version of the same chain locally.")
    agents = [("Orchestrator", ["Cloud", "Hub"], "Owns a work order end to end, plans W1–W6, asks people for approvals"),
              ("Diagnosis", ["Cloud", "Hub", "Field"], "Telemetry, alarms, manuals and past repairs → ranked causes and a safety verdict"),
              ("Dispatch", ["Cloud", "Hub"], "Scores technicians on skills, certifications, distance, workload and SLA"),
              ("Logistics", ["Cloud", "Hub"], "On-site vs workshop; parts from van → depot → warehouse → vendor"),
              ("Field assistant", ["Field"], "Procedures, LOTO checklist, live readings and findings, fully offline"),
              ("Sync service", ["Edge", "Field", "Hub", "Cloud"], "No LLM: mission packs, outbox replay, conflict rules")]
    aw, ah, ag = (CW - 2 * 0.3) / 3, 2.4, 0.3
    for i, (name, tiers_, desc) in enumerate(agents):
        col, row = i % 3, i // 3
        x, y = MX + col * (aw + ag), 1.6 + row * (ah + ag)
        d.box(s, x, y, aw, ah, fill=TINT)
        d.text(s, x + 0.25, y + 0.2, aw - 0.5, 0.45, name, size=19, bold=True)
        for j, t in enumerate(tiers_):
            fill, colr = TIER[t]
            d.chip(s, x + 0.25 + j * 0.92, y + 0.75, 0.82, 0.32, t, fill, colr, size=11)
        d.text(s, x + 0.25, y + 1.25, aw - 0.5, 1.05, desc, size=14, color=MUTED)

    # 8 - End to end ------------------------------------------------------
    s = d.slide("One work order, end to end",
                notes="Step 5 is the human gate. Whether it is automatic or needs a person comes from the "
                      "rule-based approvals table.")
    ev = ["Alarm from edge", "Diagnose", "Repair location and parts", "Rank technicians",
          "Approval", "Reserve and assign", "Mission pack to device", "Fix on site and close out"]
    sx, step = MX + 0.75, (CW - 1.5) / 7
    d.line(s, sx, 2.4, sx + 7 * step, 2.4, color=TINT2, width=4)
    for i, e in enumerate(ev):
        cx = sx + i * step
        gate = i == 4
        d.badge(s, cx, 2.4, 0.7, str(i + 1), fill=AMBER if gate else TEAL, color=TEXT if gate else WHITE, size=18)
        d.text(s, cx - 0.68, 2.95, 1.36, 1.2, e, size=14, bold=gate, align=C)
    d.text(s, sx + 4 * step - 0.75, 1.45, 1.5, 0.5, "HUMAN OR RULE GATE", size=11, bold=True, color=MUTED, align=C)
    d.box(s, MX, 4.6, (CW - 0.3) / 2, 1.5, fill=TINT,
          paras=[{"text": "Steps 1–7 move between tiers", "bold": True, "size": 17},
                 {"text": "The router runs each step at the best reachable tier: cloud when it can, hub or "
                          "device when it can't.", "size": 14, "color": MUTED}], space_after=6)
    d.box(s, MX + (CW + 0.3) / 2, 4.6, (CW - 0.3) / 2, 1.5, fill=TINT,
          paras=[{"text": "Step 8 always works offline", "bold": True, "size": 17},
                 {"text": "The mission pack plus the local Wi-Fi/BLE link to the edge gateway need no WAN at all.",
                  "size": 14, "color": MUTED}], space_after=6)

    # 9 - Section divider -------------------------------------------------
    s = d.slide("Operating in hybrid situations", dark=True, title_size=44, title_box=(0.8, 2.2, 11.5, 1.0),
                notes="The second half of the deck covers how each workflow behaves as connectivity degrades.")
    d.text(s, 0.8, 3.3, 11, 0.6, "Seven modes, one rule: degrade, never stop", size=24, color=ON_DARK)
    for i, m in enumerate(MODE):
        fill, col = MODE[m]
        cx = 1.25 + i * 1.65
        d.badge(s, cx, 5.0, 0.9, m, fill=fill, color=col, size=18)
        d.text(s, cx - 0.8, 5.55, 1.6, 0.4, MODE_NAME[m], size=13, color=ON_DARK, align=C)

    # 10 - Mode ladder ----------------------------------------------------
    s = d.slide("A link monitor picks the mode",
                notes="Every node measures cloud reachability, round-trip time, throughput and model-API health. "
                      "Recovery uses hysteresis so the mode does not flap.")
    main = [("M0", "Normal; full cloud reasoning"), ("M1", "Under 256 kbps or satellite: compact context"),
            ("M2", "Repeated drops: local first, provisional writes"), ("M4", "WAN down, depot LAN up"),
            ("M5", "Device and edge only")]
    xs = [1.5 + i * 2.58 for i in range(5)]
    cy = 3.75
    for i, (m, desc) in enumerate(main):
        fill, col = MODE[m]
        d.badge(s, xs[i], cy, 1.1, m, fill=fill, color=col, size=22)
        d.text(s, xs[i] - 1.15, cy + 0.7, 2.3, 0.4, MODE_NAME[m], size=16, bold=True, align=C)
        d.text(s, xs[i] - 1.15, cy + 1.1, 2.3, 0.85, desc, size=14, color=MUTED, align=C)
        if i < 4:
            d.arrow(s, xs[i] + 0.62, cy, xs[i + 1] - 0.62, cy, color=MUTED, width=2, both=True)
    m3x, m3y = 4.0, 1.95
    fill, col = MODE["M3"]
    d.badge(s, m3x, m3y, 0.9, "M3", fill=fill, color=col, size=18)
    d.text(s, m3x + 0.6, m3y - 0.4, 5.0, 0.8,
           [{"text": "Cloud AI down", "bold": True, "size": 16},
            {"text": "Network fine, model API failing", "size": 14, "color": MUTED}], anchor=MID)
    d.arrow(s, xs[0] + 0.4, cy - 0.45, m3x - 0.4, m3y + 0.25, color=MUTED, width=2, both=True)
    d.text(s, 8.3, 1.55, 4.4, 1.0, "Arrows run both ways: modes recover as links return, with hysteresis",
           size=14, italic=True, color=MUTED)
    fill, col = MODE["M6"]
    d.box(s, MX, 6.05, CW, 0.75, fill=None, line=MUTED, dash=True)
    d.badge(s, MX + 0.5, 6.425, 0.55, "M6", fill=fill, color=col, size=12)
    d.text(s, MX + 0.95, 6.05, CW - 1.1, 0.75,
           [{"runs": [("Sensors lost: ", {"bold": True}),
                      ("an overlay that can happen in any mode when sensors or the gateway stop reporting", {})]}],
           size=15, anchor=MID)

    # 11/12 - Matrix ------------------------------------------------------
    modes = list(MODE)
    mfills = [MODE[m] for m in modes]
    mlabels = [f"{m}  {MODE_NAME[m]}" for m in modes]
    w123 = [["Cloud model, full fleet RAG", "Live optimizer", "Learned and rule score"],
            ["Cloud model, compact edge features", "Live optimizer, small payloads", "Same as M0"],
            ["Local first, cloud second opinion", "Cloud within deadline, else hub snapshot", "Rule score locally"],
            ["Hub or field model over live cloud data", "Deterministic optimizer, no LLM", "Rule score"],
            ["Hub model and regional knowledge", "Hub snapshot and rules (provisional)", "Rule score"],
            ["Edge rules, device model, mission pack", "Self, or call the dispatcher", "Rule score; technician decides"],
            ["Guided inspection and history", "Unchanged", "Inspect on site first"]]
    w456 = [["Live ERP, hard reservation", "Mission pack and cloud knowledge", "Real-time sync"],
            ["Live ERP", "Mission pack only", "Text now, media later"],
            ["Soft reservation, confirmed on sync", "Fully local", "Outbox, replayed on reconnect"],
            ["Live ERP (data still up)", "Fully local", "Real-time sync"],
            ["Depot live, others from snapshot", "Fully local", "Queued at the hub"],
            ["Van stock only", "Fully local", "Outbox on the device"],
            ["Unchanged", "Manual readings on device", "Sensor fault gets its own WO"]]
    for title, heads, body, note in (
        ("Each mode, workflows W1–W3", ["Mode", "W1  Diagnosis", "W2  Technician", "W3  Repair location"], w123,
         "Diagnosis and dispatch degrade gracefully: from cloud reasoning, to hub or device models, to fixed rules."),
        ("Each mode, workflows W4–W6", ["Mode", "W4  Parts", "W5  Execution", "W6  Close-out"], w456,
         "Execution never needs the network. Parts and close-out switch from live to queued and confirmed later."),
    ):
        s = d.slide(title, notes=note)
        rows_ = [heads] + [[mlabels[i]] + body[i] for i in range(7)]
        d.table(s, MX, 1.55, [2.6, 3.17, 3.17, 3.16], rows_, row_h=0.66, first_col_fills=mfills, size=14)
        d.text(s, MX, 6.95, CW, 0.35, note, size=12, color=MUTED, italic=True)

    # 13 - Scenario: remote site ------------------------------------------
    def timeline(s, y, hours, segs, label_h=1.6, tick_every=1, labels=True, h=0.6):
        scale = CW / hours
        for i in range(0, hours + 1, tick_every):
            d.text(s, MX + i * scale - 0.4, y - 0.38, 0.8, 0.3, f"{i}h", size=11, color=MUTED, align=C)
        for (a, b, m, note, extra) in segs:
            fill, col = MODE[m]
            x, w = MX + a * scale, (b - a) * scale
            d.box(s, x + 0.02, y, w - 0.04, h, fill=fill, paras=f"{m}{extra}", size=14, bold=True, color=col,
                  align=C, anchor=MID, radius=0.15, margin=0.02)
            if labels and note:
                d.text(s, x + 0.05, y + h + 0.15, w - 0.1, label_h, note, size=14, color=TEXT)

    s = d.slide("Scenario: a remote desert site visit",
                notes="This timeline is the remote_site_visit scenario in the network simulator, so the "
                      "same day can be replayed in tests.")
    timeline(s, 1.95, 8, [
        (0, 1, "M0", "At depot: mission and territory packs synced", ""),
        (1, 2, "M1", "Highway: WO updates only, media deferred", ""),
        (2, 3, "M2", "Approach: last check-in, assignment provisional", ""),
        (3, 6, "M5", "On site, no coverage: diagnosis from edge rules and the device model, van stock, LOTO "
                     "checklist; findings and photos go to the outbox", ""),
        (6, 7, "M2", "Driving out: outbox sends P0–P1 first", ""),
        (7, 8, "M0", "In coverage: replay, reservations confirmed, photos upload", ""),
    ], label_h=2.4)
    d.box(s, MX, 4.75, CW, 1.0, fill=TINT, anchor=MID,
          paras=[{"runs": [("Outcome: ", {"bold": True}),
                           ("the repair is completed with no data loss, and the cloud learns about it within minutes "
                            "of reconnecting.", {})]}], size=16)

    # 14 - Scenarios: PSPS + LLM outage -----------------------------------
    s = d.slide("Scenarios: wildfire shutoff and cloud AI outage",
                notes="psps_outage and cloud_llm_outage are both simulator scenarios. In the LLM outage, data "
                      "APIs stay up, so only reasoning moves down a tier.")
    d.text(s, MX, 1.45, CW, 0.4, "Public-safety power shutoff (24 h)", size=18, bold=True)
    timeline(s, 2.3, 24, [(0, 2, "M0", "", ""), (2, 4, "M4", "", ""), (4, 16, "M5", "", " + M6  site power and sensors out"),
                          (16, 20, "M4", "", ""), (20, 24, "M0", "", "")], tick_every=4, labels=False, h=0.55)
    cols3 = [("Depot on generator", "The hub dispatches from its roster snapshot; depot stock stays live"),
             ("Site dark", "Guided inspection instead of telemetry; van stock only; everything queued"),
             ("Recovery", "The hub replays its queue to the cloud; ownership rules settle conflicts")]
    c3w = (CW - 2 * 0.3) / 3
    for i, (h, b) in enumerate(cols3):
        d.text(s, MX + i * (c3w + 0.3), 3.0, c3w, 1.1,
               [{"text": h, "bold": True, "size": 15}, {"text": b, "size": 14, "color": MUTED}], space_after=2)
    d.text(s, MX, 4.4, CW, 0.4, "Cloud model API outage (5 h)", size=18, bold=True)
    timeline(s, 5.25, 5, [(0, 1, "M0", "", ""), (1, 3, "M3", "", "  cloud AI down"), (3, 5, "M0", "", "")],
             labels=False, h=0.55)
    d.text(s, MX, 5.95, CW, 0.9,
           [{"runs": [("Data APIs stay up: ", {"bold": True}),
                      ("hub and device models reason over live CMMS, ERP and roster data. The dispatch optimizer is "
                       "deterministic, so it needs no LLM.", {"color": MUTED})]}], size=14)

    # 15 - Floor ----------------------------------------------------------
    s = d.slide("The floor: what always works at the asset",
                notes="This is the guaranteed minimum capability, even in M5 plus M6.")
    d.text(s, MX, 1.5, CW, 0.5, "Even with no network and no sensors (M5 + M6), a technician at the asset can still:",
           size=18, color=MUTED)
    floor = [("Open the asset's knowledge", "Manuals, procedures, LOTO checklist and past fixes, from the mission pack"),
             ("Get guided diagnosis", "The on-device model reasons over that pack and the technician's observations"),
             ("Use van stock", "See what's in the van and record parts as they're used"),
             ("Record everything", "Findings, parts used and photos, synced later with no data loss")]
    fw, fg = (CW - 0.3) / 2, 0.3
    for i, (h, b) in enumerate(floor):
        col, row = i % 2, i // 2
        x, y = MX + col * (fw + fg), 2.3 + row * 2.2
        d.box(s, x, y, fw, 1.95, fill=TINT)
        d.badge(s, x + 0.65, y + 0.975, 0.85, str(i + 1), fill=AMBER, size=22)
        d.text(s, x + 1.35, y + 0.25, fw - 1.6, 1.5,
               [{"text": h, "bold": True, "size": 19}, {"text": b, "size": 15, "color": MUTED}],
               anchor=MID, space_after=4)

    # 16 - Data and bandwidth ---------------------------------------------
    s = d.slide("Moving data over thin links",
                notes="Mission packs are the most important offline mechanism. Priority classes decide what "
                      "uses scarce bandwidth first.")
    d.box(s, MX, 1.55, 5.2, 5.25, fill=TINT)
    d.text(s, MX + 0.3, 1.75, 4.6, 0.45, "Mission packs", size=19, bold=True)
    d.text(s, MX + 0.3, 2.25, 4.6, 0.6, "Pre-staged to the device on assignment, plus nightly territory packs",
           size=14, color=MUTED)
    d.text(s, MX + 0.3, 2.95, 4.6, 2.6,
           ["Manual sections and a local search index", "Last repairs on this asset and similar fixes",
            "Likely parts for the top diagnoses", "Recent telemetry summary and alarms",
            "Site access notes and hazards"], size=15, bullet=True, space_after=6)
    d.text(s, MX + 0.3, 5.65, 4.6, 1.0,
           [{"runs": [("At the edge: ", {"bold": True}),
                      ("send features and alarms, not raw waveforms.", {"color": MUTED})]}], size=14)
    d.text(s, 6.2, 1.55, 6.5, 0.45, "Traffic priority classes", size=19, bold=True)
    pcls = [("P0", "Safety", "Trip alarms, LOTO confirmations", "All modes, any link", "B83227", WHITE),
            ("P1", "Control", "Assignments, reservations, status", "M0–M2", "D9732B", WHITE),
            ("P2", "Context", "Diagnosis, telemetry features", "M0–M2, compact", "F2C230", TEXT),
            ("P3", "Knowledge", "Mission-pack deltas, history", "M0, M1 off-peak", "1B8A8F", WHITE),
            ("P4", "Bulk", "Photos, video, raw waveforms", "M0 only, depot Wi-Fi", "5B6B73", WHITE)]
    for i, (p, n, ex, allowed, fill, col) in enumerate(pcls):
        y = 2.15 + i * 0.93
        d.badge(s, 6.6, y + 0.4, 0.7, p, fill=fill, color=col, size=15)
        d.text(s, 7.1, y, 3.4, 0.85, [{"text": n, "bold": True, "size": 16}, {"text": ex, "size": 14, "color": MUTED}],
               anchor=MID)
        d.text(s, 10.65, y, 2.05, 0.85, allowed, size=14, bold=True, anchor=MID)

    # 17 - Sync -----------------------------------------------------------
    s = d.slide("Sync without conflicts: every record has an owner",
                notes="Ownership rules instead of generic merges. Offline decisions are always proposals.")
    owners = [("Cloud", "Assignments, reservations, purchase orders"), ("Edge", "Telemetry and alarms"),
              ("Field", "On-site observations, parts used from the van")]
    ow = (CW - 2 * 0.3) / 3
    for i, (t, b) in enumerate(owners):
        fill, col = TIER[t]
        x = MX + i * (ow + 0.3)
        d.box(s, x, 1.6, ow, 1.55, fill=fill, color=col, anchor=MID,
              paras=[{"text": f"{'Device' if t == 'Field' else t} owns", "bold": True, "size": 18},
                     {"text": b, "size": 15}], space_after=4)
    flow = ["Offline decision", "Stored as provisional proposal", "Sync on reconnect",
            "Cloud confirms or counter-proposes", "Technician notified"]
    fx, fs = MX + 0.9, (CW - 1.8) / 4
    d.line(s, fx, 4.0, fx + 4 * fs, 4.0, color=TINT2, width=4)
    for i, f in enumerate(flow):
        cx = fx + i * fs
        d.badge(s, cx, 4.0, 0.6, str(i + 1), fill=TEAL, color=WHITE, size=16)
        d.text(s, cx - 1.05, 4.45, 2.1, 0.8, f, size=14, align=C)
    rules = [("Idempotency keys", "Replaying the outbox never applies a write twice"),
             ("Append-only data", "Findings, readings and photos never conflict"),
             ("Parts collision", "The earlier, higher-priority WO wins; the other gets an alternative source")]
    for i, (h, b) in enumerate(rules):
        x = MX + i * (ow + 0.3)
        d.box(s, x, 5.45, ow, 1.35, fill=TINT, paras=[{"text": h, "bold": True, "size": 16},
                                                      {"text": b, "size": 14, "color": MUTED}], space_after=3)

    # 18 - Safety and approvals -------------------------------------------
    s = d.slide("Safety and rule-based approvals",
                notes="The approvals file is evaluated by deterministic code, not an LLM, so it behaves "
                      "the same at every tier, offline included.")
    safety = [("Edge safety wins", "An 'unsafe to run' rule at the edge can't be overridden by any agent"),
              ("Read-only to equipment", "No control tools; setpoint changes stay with SCADA and PLC safety"),
              ("Staleness guardrails", "Old data is never shown as live; every decision is audit-logged")]
    for i, (h, b) in enumerate(safety):
        y = 1.6 + i * 1.75
        d.box(s, MX, y, 4.3, 1.55, fill=TINT, paras=[{"text": h, "bold": True, "size": 17},
                                                     {"text": b, "size": 14, "color": MUTED}], space_after=4)
    appr = [["Action", "Condition", "Outcome"],
            ["Shutdown", "Edge safety rule fired", "Auto, planner notified"],
            ["Shutdown", "Any other case", "Site operator"],
            ["Dispatch", "Routine or soon, skills matched, on shift", "Auto"],
            ["Dispatch", "Urgent, missing skills or overtime", "Planner"],
            ["Parts", "Van or depot stock, under $1,000", "Auto"],
            ["Parts", "$1,000 or more, or vendor order", "Regional manager"],
            ["Workshop", "Any transfer to a workshop", "Planner"],
            ["Offline", "Would otherwise be auto", "Auto, provisional"]]
    d.table(s, 5.2, 1.6, [1.5, 4.0, 2.03], appr, row_h=0.575, size=14)

    # 19 - Demo decisions -------------------------------------------------
    s = d.slide("Demo scope: decisions made",
                notes="These answer the open questions from the design document, section 11.")
    dec = [("Systems of record", "Our own MCP servers", "No commercial CMMS/ERP adapters; JSON or SQLite backends"),
           ("Equipment data", "Replayed from files", "Per-asset JSONL telemetry stands in for OPC-UA or Modbus"),
           ("Scale", "Under 50 of each", "6 depots, 12 sites, about 30 assets, 12 technicians"),
           ("Depot network", "Yes, hubs in scope", "Every depot runs a T2 hub; mode M4 is first-class"),
           ("Approvals", "Rule-based", "A declarative rules file, evaluated the same at every tier"),
           ("Data limits", "None", "Only bandwidth classes limit what goes to the cloud")]
    tw, th = (CW - 2 * 0.3) / 3, 2.4
    for i, (q, a, e) in enumerate(dec):
        col, row = i % 3, i // 3
        x, y = MX + col * (tw + 0.3), 1.6 + row * (th + 0.3)
        d.box(s, x, y, tw, th, fill=TINT)
        d.text(s, x + 0.25, y + 0.2, tw - 0.5, 0.35, q.upper(), size=12, bold=True, color=TEAL)
        d.text(s, x + 0.25, y + 0.6, tw - 0.5, 0.5, a, size=20, bold=True)
        d.text(s, x + 0.25, y + 1.2, tw - 0.5, 1.1, e, size=14, color=MUTED)

    # 20 - Roadmap --------------------------------------------------------
    s = d.slide("Roadmap and how we'll measure it",
                notes="Phase 1 is done: contracts plus fleet, telemetry and network simulators, with 47 tests passing.")
    phases = ["Contracts and simulator", "Cloud MVP (M0)", "Field tier and mission packs", "Router and modes",
              "Edge integration", "Hub tier", "Pilot, then scale"]
    px, ps = MX + 0.8, (CW - 1.6) / 6
    d.line(s, px, 2.3, px + 6 * ps, 2.3, color=TINT2, width=4)
    for i, ph in enumerate(phases):
        cx = px + i * ps
        if i == 0:
            fill, col, tag = MODE["M0"][0], WHITE, "DONE"
        elif i == 1:
            fill, col, tag = AMBER, TEXT, "NEXT"
        else:
            fill, col, tag = TINT2, TEXT, ""
        d.badge(s, cx, 2.3, 0.75, str(i + 1), fill=fill, color=col, size=18)
        if tag:
            d.text(s, cx - 0.8, 1.45, 1.6, 0.35, tag, size=12, bold=True, align=C,
                   color=MODE["M0"][0] if i == 0 else "9A6B00")
        d.text(s, cx - 0.8, 2.85, 1.6, 1.0, ph, size=14, align=C, bold=i < 2)
    d.text(s, MX, 4.45, CW, 0.4, "Success metrics", size=18, bold=True)
    mets = ["Mean time to diagnose", "First-time fix rate", "Drive time per work order",
            "Parts-not-available rate", "WOs done in degraded modes with no data loss"]
    mw = (CW - 4 * 0.25) / 5
    for i, m in enumerate(mets):
        d.box(s, MX + i * (mw + 0.25), 5.0, mw, 1.7, fill=TINT, paras=m, size=15, bold=True, anchor=MID, align=C)

    # 21 - Close ----------------------------------------------------------
    s = d.slide("Phase 1 is already running", dark=True, title_size=40, title_box=(0.8, 0.8, 11.5, 0.9),
                notes="Close with what exists today and the next step.")
    stats = [("8", "MCP tool contracts"), ("7", "operating modes simulated"), ("6", "network scenarios"),
             ("47", "tests passing")]
    sw4 = 11.7 / 4
    for i, (n, l) in enumerate(stats):
        x = 0.8 + i * sw4
        d.text(s, x, 2.0, sw4 - 0.3, 1.3, n, size=66, bold=True, color=AMBER)
        d.text(s, x, 3.3, sw4 - 0.3, 0.8, l, size=18, color=ON_DARK)
    d.text(s, 0.8, 4.6, 11.7, 0.5, "Next: phase 2, the cloud MVP", size=24, bold=True, color=WHITE)
    d.text(s, 0.8, 5.2, 11.7, 1.5,
           ["Our own MCP servers, seeded from the simulated fleet",
            "Orchestrator and specialist agents running W1–W4 end to end, with rule-based approvals",
            "Then phase 3: field tier, mission packs and the offline outbox"],
           size=16, color=ON_DARK, bullet=True, space_after=6)

    d.save(out)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "docs" / "hybrid-ai-design.pptx"
    build(out)
    print(f"wrote {out}")
