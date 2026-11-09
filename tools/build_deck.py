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

MODE = {  # operating modes (fill, text)
    "ONLINE": ("2E8B57", WHITE), "LIMITED": ("F2C230", TEXT), "OFFLINE": ("B83227", WHITE),
}
MODE_NAME = {"ONLINE": "Online", "LIMITED": "Limited", "OFFLINE": "Offline"}
EVENT = ("7A5AA6", WHITE)  # cloud AI outage / sensors lost
TIER = {  # places (fill, text)
    "Cloud": (SLATE, WHITE), "Edge": ("C98A00", WHITE), "Device": (TEAL, WHITE),
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
    places = ["Device", "Edge", "Cloud"]

    def place_chip(s, x, y, w, h, place, size=12, label=None):
        fill, col = TIER[place]
        d.chip(s, x, y, w, h, label or place, fill, col, size=size)

    def mode_chip(s, x, y, w, h, m, size=12, label=None):
        fill, col = MODE[m]
        d.chip(s, x, y, w, h, label or MODE_NAME[m], fill, col, size=size)

    # 1 - Title ---------------------------------------------------------
    s = d.slide("hybrid-ai", dark=True, title_size=60, title_box=(0.8, 1.7, 7.6, 1.1),
                notes="hybrid-ai is a design for MCP-based agents that help maintain a California compressor "
                      "fleet, built to keep working when connectivity or the cloud fails.")
    d.text(s, 0.8, 2.95, 7.4, 1.3, "Field-service agents that keep working when the network doesn't", size=28, color=ON_DARK)
    d.text(s, 0.8, 4.6, 7.4, 0.9, ["MCP agent design for a California compressor fleet", "Design v0.4  ·  November 2026"],
           size=16, color=ON_DARK_MUTED, space_after=4)
    for i, p in enumerate(["Cloud", "Edge", "Device"]):
        fill, col = TIER[p]
        y = 1.8 + i * 1.3
        d.box(s, 9.3, y, 3.2, 0.85, fill=fill, paras=p, size=22, bold=True, color=col, anchor=MID, align=C, radius=0.3)
        if i < 2:
            d.arrow(s, 10.9, y + 0.87, 10.9, y + 1.28, color=ON_DARK_MUTED, width=1.5, dash=True, both=True)

    # 2 - Problem -------------------------------------------------------
    s = d.slide("Six decisions behind every compressor issue",
                notes="Every issue runs the same chain from W1 to W6. The constraints at the bottom are what make "
                      "a cloud-only design fail at remote California sites.")
    flows = [("W1", "Triage", "What is wrong, how bad, safe to run?"), ("W2", "Technician", "Who is qualified, close and available?"),
             ("W3", "Location", "Fix on site or pull to a workshop?"), ("W4", "Parts", "Van, depot, warehouse or order? Reserve them"),
             ("W5", "Execution", "Repair plan, manuals, LOTO at the compressor"), ("W6", "Close-out", "Record the fix so triage gets smarter")]
    cw, gap = 1.85, 0.2
    for i, (code, name, q) in enumerate(flows):
        x = MX + i * (cw + gap)
        d.box(s, x, 1.65, cw, 2.55, fill=TINT)
        d.badge(s, x + cw / 2, 2.15, 0.62, code, fill=AMBER, size=14)
        d.text(s, x + 0.12, 2.6, cw - 0.24, 0.4, name, size=17, bold=True, align=C)
        d.text(s, x + 0.12, 3.05, cw - 0.24, 1.1, q, size=14, color=MUTED, align=C)
    d.text(s, MX, 4.55, CW, 0.4, "What makes it hard here", size=20, bold=True)
    cons = [("Connectivity gaps", "Valley, desert and foothill dead zones; wildfire power shutoffs for days"),
            ("Heavy live data", "Vibration, pressure and alarms can't all stream raw over weak links"),
            ("Heavy knowledge", "Manuals and years of repair history are gigabytes"),
            ("Safety and cost", "Rules or people approve dispatch, shutdowns and parts; no acting on stale data")]
    cw4 = (CW - 3 * 0.3) / 4
    for i, (h, b) in enumerate(cons):
        d.box(s, MX + i * (cw4 + 0.3), 5.05, cw4, 1.8, fill=WHITE, line=TINT2,
              paras=[{"text": h, "bold": True, "size": 16}, {"text": b, "size": 14, "color": MUTED}], space_after=4)

    # 3 - Design goal -----------------------------------------------------
    s = d.slide("Design goal", dark=True, title_size=20, title_box=(0.8, 0.8, 6, 0.5), notes="The one idea everything else hangs on.")
    s.shapes.title.text_frame.paragraphs[0].runs[0].font.color.rgb = rgb(AMBER)
    d.text(s, 0.8, 1.45, 11.7, 1.9, "Every workflow has a cloud-best answer and a local good-enough answer, behind the same interface",
           size=32, bold=True, color=WHITE)
    pillars = [("1", "One MCP contract everywhere", "Same tools and schemas in the cloud, at the edge and on the device"),
               ("2", "Agents move to where they can run", "A router sends each request to cloud, edge or device by mode"),
               ("3", "Every answer says where and how fresh", "Place, age, provisional or confirmed, time and tokens")]
    pw = (11.7 - 2 * 0.4) / 3
    for i, (n, h, b) in enumerate(pillars):
        x = 0.8 + i * (pw + 0.4)
        d.badge(s, x + 0.35, 4.25, 0.7, n, fill=AMBER, size=20)
        d.text(s, x, 4.8, pw, 0.85, h, size=20, bold=True, color=WHITE)
        d.text(s, x, 5.7, pw, 1.0, b, size=16, color=ON_DARK)

    # 4 - Three places ----------------------------------------------------
    s = d.slide("Three places, each with its own agents and data",
                notes="Device, edge and cloud each hold databases and can run models. The cloud is authoritative; "
                      "the edge sits next to the compressor; the device goes everywhere the technician goes.")
    cols = [("Device", "Technician tablet in the service van", "Repair-rec model copy, small LLM",
             ["Mission pack DB: plan copy, manuals index, history", "Outbox: queued updates", "Van stock"]),
            ("Edge", "Site gateway + depot edge server", "Repair-rec copy, mid-size LLM, rules",
             ["Telemetry buffer (7–30 days)", "Safety rules", "Depot mirror: stock, roster, regional knowledge"]),
            ("Cloud", "Authoritative", "Claude; repair-rec model registry",
             ["Repair recommendations DB", "Model registry (repair-rec-1.0)", "Work orders + ERP", "Knowledge base"])]
    pw = (CW - 2 * 0.6) / 3
    for i, (p, sub, model, dbs) in enumerate(cols):
        x = MX + i * (pw + 0.6)
        fill, col = TIER[p]
        d.box(s, x, 1.55, pw, 0.95, fill=fill, color=col, anchor=MID, paras=[{"text": p, "bold": True, "size": 20}, {"text": sub, "size": 13}])
        d.box(s, x, 2.6, pw, 0.6, fill=TINT, paras=[{"runs": [("Models: ", {"bold": True}), (model, {})]}], size=14, anchor=MID)
        d.text(s, x + 0.05, 3.35, pw, 0.35, "DATABASES", size=11, bold=True, color=MUTED)
        for j, db in enumerate(dbs):
            d.box(s, x, 3.7 + j * 0.62, pw, 0.52, fill=WHITE, line=TINT2, paras=db, size=13, anchor=MID)
        if i < 2:
            d.arrow(s, x + pw + 0.05, 2.02, x + pw + 0.55, 2.02, color=MUTED, width=2, both=True)
    d.text(s, MX, 6.35, CW, 0.5, "Device ↔ Edge: local Wi-Fi/BLE, always.   Device / Edge ↔ Cloud: the WAN, which is Online, Limited or down.",
           size=14, color=MUTED, italic=True)

    # 5 - Contract --------------------------------------------------------
    s = d.slide("One MCP contract, many implementations",
                notes="Agents never know which place answered unless they read the provenance fields, and they "
                      "tell the technician whenever data is provisional or stale.")
    tools = ["diagnose_issue", "find_technicians", "recommend_repair_location", "check_parts",
             "reserve_parts", "search_knowledge", "get_live_telemetry", "update_work_order"]
    d.text(s, MX, 1.5, 6.0, 0.4, "8 tools, same JSON Schemas everywhere", size=18, bold=True)
    for i, t in enumerate(tools):
        d.box(s, MX + (i % 2) * 3.05, 2.05 + (i // 2) * 0.75, 2.9, 0.6, fill=TINT, paras=t, size=12, font=MONO, anchor=MID, bold=True, margin=0.12)
    d.text(s, MX, 5.15, 5.95, 1.3, "Only the data behind them changes: depth and freshness. Swapping a backend never changes the agents.",
           size=14, color=MUTED)
    d.text(s, 7.15, 1.5, 5.55, 0.4, "Every response carries provenance", size=18, bold=True)
    code = ['{', '  "result": { … },', '  "source_tier": "device",', '  "as_of": "2026-11-08T14:02Z",',
            '  "staleness_s": 18240,', '  "confidence": "provisional",', '  "authoritative": false', '}']
    d.box(s, 7.15, 2.05, 5.55, 3.35, fill=INK, paras=code, font=MONO, size=15, color=ON_DARK, margin=0.3, anchor=MID)
    d.text(s, 7.15, 5.6, 5.55, 0.9, '"Roster is 3 h old, so this assignment is provisional until sync."', size=15, italic=True, color=TEAL)

    # 6 - Router ----------------------------------------------------------
    s = d.slide("The router decides where each request runs",
                notes="The router is a small local service on every node. It is what makes the agents move between places.")
    steps = [("Check mode", "Online, Limited or Offline, plus events"), ("Try places in order", "Policy order per tool"),
             ("Enforce a deadline", "3 s on a Limited link, then fall back"), ("Queue writes", "Cloud unreachable: write goes to the outbox"),
             ("Label and log", "Place, why, age, time and tokens")]
    sw, sg = 2.06, 0.45
    for i, (h, b) in enumerate(steps):
        x = MX + i * (sw + sg)
        d.badge(s, x + sw / 2, 2.05, 0.75, str(i + 1), fill=AMBER, size=20)
        d.text(s, x, 2.6, sw, 0.5, h, size=17, bold=True, align=C)
        d.text(s, x, 3.1, sw, 1.0, b, size=14, color=MUTED, align=C)
        if i < 4:
            d.arrow(s, x + sw / 2 + 0.45, 2.05, x + sw + sg + sw / 2 - 0.45, 2.05, color=MUTED, width=2)
    d.text(s, MX, 4.55, CW, 0.4, "Example policies", size=18, bold=True)
    pol = [("diagnose_issue", ["Cloud", "Edge", "Device"]), ("get_live_telemetry", ["Edge", "Cloud"]), ("check_parts", ["Cloud", "Edge", "Device"])]
    for i, (tool, order) in enumerate(pol):
        y = 5.1 + i * 0.6
        d.text(s, MX, y, 3.4, 0.45, tool, size=15, font=MONO, bold=True, anchor=MID)
        for j, t in enumerate(order):
            x = 4.2 + j * 1.9
            place_chip(s, x, y + 0.02, 1.4, 0.42, t, size=13)
            if j < len(order) - 1:
                d.arrow(s, x + 1.45, y + 0.23, x + 1.85, y + 0.23, color=MUTED, width=1.5)
    d.text(s, 9.9, 5.1, 2.8, 1.6, "Answers from the edge or device come back provisional", size=14, color=MUTED, italic=True)

    # 7 - Agents ----------------------------------------------------------
    s = d.slide("Specialist agents, coordinated by an orchestrator",
                notes="Chips show where each agent can run. The next section shows where they run in each mode.")
    agents = [("Orchestrator", ["Cloud", "Device"], "Owns a work order end to end, plans W1–W6, asks for approvals"),
              ("Repair-rec model (ML)", ["Cloud", "Edge", "Device"], "A small trained model ranks causes from telemetry, symptoms and history. Same weights everywhere, no tokens"),
              ("Dispatch", ["Cloud", "Edge"], "Deterministic scoring on skills, certifications, distance, workload and SLA"),
              ("Logistics", ["Cloud", "Edge", "Device"], "On site vs workshop; parts from van → depot → warehouse → vendor"),
              ("Field assistant", ["Device"], "Repair plan, LOTO, live readings and findings; uses the best model it can reach"),
              ("Safety rules + Sync", ["Edge", "Device"], "Trip rules next to the sensors; outbox replay and mission packs")]
    aw, ah, ag = (CW - 2 * 0.3) / 3, 2.4, 0.3
    for i, (name, tiers_, desc) in enumerate(agents):
        x, y = MX + (i % 3) * (aw + ag), 1.6 + (i // 3) * (ah + ag)
        d.box(s, x, y, aw, ah, fill=TINT)
        d.text(s, x + 0.25, y + 0.2, aw - 0.5, 0.45, name, size=19, bold=True)
        for j, t in enumerate(tiers_):
            place_chip(s, x + 0.25 + j * 1.0, y + 0.75, 0.9, 0.32, t, size=11)
        d.text(s, x + 0.25, y + 1.25, aw - 0.5, 1.05, desc, size=14, color=MUTED)

    # 8 - End to end ------------------------------------------------------
    s = d.slide("One work order, end to end", notes="Step 5 is the gate: rules approve routine work; the rest goes to a person.")
    ev = ["Alarm from edge", "Diagnose", "Repair location and parts", "Rank technicians", "Approval", "Reserve and assign",
          "Plan into mission pack", "Repair on site and close out"]
    sx, step = MX + 0.75, (CW - 1.5) / 7
    d.line(s, sx, 2.4, sx + 7 * step, 2.4, color=TINT2, width=4)
    for i, e in enumerate(ev):
        cx, gate = sx + i * step, i == 4
        d.badge(s, cx, 2.4, 0.7, str(i + 1), fill=AMBER if gate else TEAL, color=TEXT if gate else WHITE, size=18)
        d.text(s, cx - 0.68, 2.95, 1.36, 1.2, e, size=14, bold=gate, align=C)
    d.text(s, sx + 4 * step - 0.75, 1.45, 1.5, 0.5, "RULE OR PERSON", size=11, bold=True, color=MUTED, align=C)
    d.box(s, MX, 4.6, (CW - 0.3) / 2, 1.5, fill=TINT, space_after=6,
          paras=[{"text": "Steps 1–7 move between places", "bold": True, "size": 17},
                 {"text": "The router runs each step in the cloud when it can, at the edge or on the device when it can't.", "size": 14, "color": MUTED}])
    d.box(s, MX + (CW + 0.3) / 2, 4.6, (CW - 0.3) / 2, 1.5, fill=TINT, space_after=6,
          paras=[{"text": "Step 8 always works offline", "bold": True, "size": 17},
                 {"text": "The repair plan is in the mission pack DB, and the device talks to the edge over the local link.", "size": 14, "color": MUTED}])

    # 9 - Section divider -------------------------------------------------
    s = d.slide("Operating in hybrid situations", dark=True, title_size=44, title_box=(0.8, 2.2, 11.5, 1.0),
                notes="Three modes for the link, two events that can happen in any mode.")
    d.text(s, 0.8, 3.3, 11, 0.6, "Three modes, two events, one rule: degrade, never stop", size=24, color=ON_DARK)
    for i, m in enumerate(MODE):
        mode_chip(s, 0.8 + i * 2.4, 4.6, 2.1, 0.62, m, size=18)
    for i, e in enumerate(["Cloud AI outage", "Sensors lost"]):
        d.chip(s, 8.3 + i * 2.3, 4.6, 2.1, 0.62, e, EVENT[0], EVENT[1], size=15)
    d.text(s, 0.8, 5.35, 7, 0.4, "MODES", size=12, bold=True, color=ON_DARK_MUTED)
    d.text(s, 8.3, 5.35, 4.5, 0.4, "EVENTS", size=12, bold=True, color=ON_DARK_MUTED)

    # 10 - Modes and events ----------------------------------------------
    s = d.slide("Three modes, two events",
                notes="A link monitor picks the mode with hysteresis. Events are independent of the mode.")
    md = [("ONLINE", "Cloud reachable at normal speed", "Cloud reasons and decides; edge serves live data and safety; device shows it all"),
          ("LIMITED", "Slow or intermittent: one bar, satellite, coverage edges", "Edge model next to the data; device answers first; cloud in windows, within deadline"),
          ("OFFLINE", "No WAN; device and edge still talk locally", "Edge model and rules plus the device and mission pack; dispatch unavailable")]
    mw = (CW - 2 * 0.3) / 3
    for i, (m, what, where) in enumerate(md):
        x = MX + i * (mw + 0.3)
        mode_chip(s, x, 1.6, mw, 0.6, m, size=18)
        d.box(s, x, 2.35, mw, 2.25, fill=TINT, space_after=6,
              paras=[{"text": what, "bold": True, "size": 16}, {"text": where, "size": 14, "color": MUTED}])
        if i < 2:
            d.arrow(s, x + mw + 0.03, 1.9, x + mw + 0.27, 1.9, color=MUTED, width=1.5, both=True)
    ev_rows = [("Cloud AI outage", "Model API failing, network fine", "Reasoning moves to the edge model; data, dispatch and the database stay live in the cloud"),
               ("Sensors lost", "Gateway or sensors dark, e.g. site power cut", "No live data: diagnosis moves to the device as guided inspection")]
    for i, (e, what, eff) in enumerate(ev_rows):
        y = 4.9 + i * 0.95
        d.chip(s, MX, y + 0.12, 2.2, 0.5, e, EVENT[0], EVENT[1], size=13)
        d.text(s, MX + 2.45, y, CW - 2.45, 0.8, [{"runs": [(what + ". ", {"bold": True}), (eff, {"color": MUTED})]}], size=15, anchor=MID)

    # 11 - Where agents run per mode ---------------------------------------
    s = d.slide("Where each agent runs, mode by mode",
                notes="This is what the dashboard's 'Where agents run' view animates: the same agents move between "
                      "places as the link changes.")
    rows = [("Orchestrator", ["Cloud", "Cloud", "Device"], ""),
            ("Repair-rec model", ["Cloud", "Edge", "Edge"], "→ Device copy when sensors lost · no tokens"),
            ("Dispatch", ["Cloud", "Edge", None], "Offline: call the dispatcher"),
            ("Logistics (parts)", ["Cloud", "Edge", "Device"], "Live ERP → depot mirror → van stock"),
            ("Assistant model", ["Cloud", "Edge", "Edge"], "→ Device when the edge is dark"),
            ("Repair plan", ["Cloud", "Device", "Device"], "Cloud DB → mission pack DB copy"),
            ("Step updates", ["Cloud", "Device", "Device"], "Queued in the outbox, replayed once")]
    hx, colw = MX + 2.75, 1.75
    for j, m in enumerate(MODE):
        mode_chip(s, hx + j * (colw + 0.15), 1.5, colw, 0.45, m, size=14)
    d.text(s, hx + 3 * (colw + 0.15) + 0.1, 1.5, 3.2, 0.45, "NOTES", size=11, bold=True, color=MUTED, anchor=MID)
    for i, (agent, where, note) in enumerate(rows):
        y = 2.15 + i * 0.66
        d.text(s, MX, y, 2.65, 0.5, agent, size=15, bold=True, anchor=MID)
        for j, p in enumerate(where):
            x = hx + j * (colw + 0.15)
            if p:
                place_chip(s, x + 0.15, y + 0.06, colw - 0.3, 0.4, p, size=12)
            else:
                d.chip(s, x + 0.15, y + 0.06, colw - 0.3, 0.4, "unavailable", TINT2, MUTED, size=11, bold=False)
        d.text(s, hx + 3 * (colw + 0.15) + 0.1, y, 3.3, 0.55, note, size=12, color=MUTED, anchor=MID)

    # Animated: agents moving between device, edge and cloud (click through in Slide Show)
    from build_agent_motion import add_motion_slide
    add_motion_slide(d)

    # Running for real: the live demo ---------------------------------------
    s = d.slide("Running for real: four processes",
                notes="The live demo (python -m hybrid_ai.live, or the deployed hybrid-ai-live service). Cloud and edge are "
                      "real MCP servers; the device routes real MCP calls through a TCP proxy that delays, flaps or cuts "
                      "links. The table shows one measured run. No LLM calls are made: answers are templated.")
    procs = [("Device", ":8803", "Router + link monitor\nmission pack + outbox (SQLite)"),
             ("Edge", ":8802", "MCP server\ntelemetry files, model copy"),
             ("Cloud", ":8801", "MCP server\nrepair recommendations DB")]
    pw2 = 3.0
    for i, (pl, port, desc) in enumerate(procs):
        x = MX + i * (pw2 + 0.95)
        fill, col = TIER[pl]
        d.box(s, x, 1.6, pw2, 1.35, fill=fill, color=col, anchor=MID, align=C,
              paras=[{"text": f"{pl}  {port}", "bold": True, "size": 17}] + [{"text": t, "size": 12} for t in desc.split("\n")])
        if i < 2:
            d.arrow(s, x + pw2 + 0.05, 2.27, x + pw2 + 0.9, 2.27, color=MUTED, width=2, both=True)
    d.box(s, MX, 3.2, 3 * pw2 + 2 * 0.95, 0.5, fill=TINT, size=13, anchor=MID, align=C,
          paras=[{"runs": [("Every arrow goes through the network simulator (:8810):  ", {"bold": True}), ("Online 40 ms · Limited flaps, 250 ms · Offline refuses the WAN · sensors lost cuts the edge", {})]}])
    rows = [["Situation", "Where the request actually ran", "Measured"],
            ["Online: what's wrong?", "Cloud (model, fleet telemetry)", "266 ms"],
            ["Limited: what's wrong?", "Edge (local first)", "67 ms"],
            ["Offline: lockout steps", "Device outbox (no WAN)", "queued"],
            ["Sensors lost: what's wrong?", "Device (symptoms only)", "0.2 ms"],
            ["Back online", "5 writes replayed to the cloud DB, once each", "270–370 ms each"]]
    d.table(s, MX, 3.95, [3.6, 5.0, 2.4], rows, row_h=0.48, size=13, header_size=13)

    # The first AI agent ---------------------------------------------------
    s = d.slide("The first AI agent: repair steps from the manuals",
                notes="hybrid_ai.agents.manual_agent. Claude Opus 5.5 runs a tool-use loop over three tools and must cite "
                      "the manual passage behind every step. In the cloud it needs an API key; the edge and the device "
                      "answer retrieval only from their own manual copies, so the technician always gets a cited procedure.")
    flow = [("Technician asks", "\"What's wrong and how do I fix it?\"", TINT, TEXT),
            ("Claude Opus 5.5", "tool-use loop, effort medium", SLATE, WHITE),
            ("Cited answer", "cause · lockout first · numbered steps [MAN-…] · parts · test-run checks", "DCEFE3", TEXT)]
    fy = 1.6
    for i, (h, b, fill, col) in enumerate(flow):
        y = fy + i * 1.62
        d.box(s, MX, y, 5.2, 1.2, fill=fill, color=col, anchor=MID,
              paras=[{"text": h, "bold": True, "size": 17}, {"text": b, "size": 13}])
        if i < 2:
            d.arrow(s, MX + 2.6, y + 1.22, MX + 2.6, y + 1.6, color=MUTED, width=2)
    tools = [("search_service_manual", "BM25 over 117 manual passages and repair notes"),
             ("get_work_order", "symptoms, alarms, hazards, the model's ranked causes"),
             ("get_repair_history", "past repairs on this compressor")]
    for i, (t, desc) in enumerate(tools):
        y = fy + 0.5 + i * 0.56
        d.box(s, MX + 5.55, y, 2.15, 0.48, fill=TINT, paras=t, size=10, font=MONO, bold=True, anchor=MID, margin=0.08)
        d.text(s, MX + 7.8, y, 4.3, 0.48, desc, size=12, color=MUTED, anchor=MID)
    d.arrow(s, MX + 5.25, fy + 1.9, MX + 5.5, fy + 1.9, color=MUTED, width=1.5, both=True)
    d.text(s, MX + 5.55, fy, 6.5, 0.4, "Tools the agent calls", size=13, bold=True)
    rows = [["Place", "Who answers recommend_repair"],
            ["Cloud", "The Claude agent (needs an API key; up to 120 s)"],
            ["Edge", "Retrieval only, from its own copy of the manuals"],
            ["Device", "Retrieval only, from the mission pack"]]
    gt = d.table(s, MX + 5.55, 4.15, [1.4, 5.15], rows, row_h=0.46, size=13, header_size=13)
    for r, place in enumerate(["Cloud", "Edge", "Device"], start=1):
        cell = gt.table.cell(r, 0)
        cell.fill.solid()
        cell.fill.fore_color.rgb = rgb(TIER[place][0])
        for run in cell.text_frame.paragraphs[0].runs:
            run.font.color.rgb = rgb(TIER[place][1])
    d.box(s, MX + 5.55, 6.15, 6.55, 0.62, fill="FDEEC2", size=13, anchor=MID,
          paras=[{"runs": [("Grounding rules: ", {"bold": True}),
                           ("cite a passage for every step · only retrieved part numbers · say when the manual doesn't cover it", {})]}])

    # Implementation architecture (shared with the brief deck)
    from build_arch_slide import add_arch_slide
    add_arch_slide(d)

    # 12 - Mode x workflow -----------------------------------------------
    s = d.slide("Each mode, each workflow", notes="What every workflow does in each mode, with the place that answers.")
    tbl = [["Workflow", "Online", "Limited", "Offline"],
           ["W1 Diagnosis", "Repair-rec model, cloud copy", "Repair-rec model, edge copy", "Edge copy (device copy if sensors lost)"],
           ["W2 Technician", "Live optimizer", "Cloud within deadline, else edge snapshot", "Unavailable: call the dispatcher"],
           ["W3 Location", "Learned + rule score", "Rule score", "Rule score; technician decides"],
           ["W4 Parts", "Live ERP, hard reservation", "Depot mirror, soft reservation", "Van stock only"],
           ["W5 Execution", "Repair plan from the cloud DB", "Plan from the mission pack", "Plan from the mission pack"],
           ["W6 Close-out", "Real-time sync", "Text in windows, media later", "Outbox on the device"]]
    gt = d.table(s, MX, 1.55, [2.3, 3.27, 3.27, 3.26], tbl, row_h=0.68, size=14)
    for j, m in enumerate(MODE):
        cell = gt.table.cell(0, j + 1)
        cell.fill.solid()
        cell.fill.fore_color.rgb = rgb(MODE[m][0])
        for r in cell.text_frame.paragraphs[0].runs:
            r.font.color.rgb = rgb(MODE[m][1])

    # 13 - Remote site scenario --------------------------------------------
    def timeline(s, y, hours, segs, tick_every=1, h=0.6, labels=True, label_h=2.0):
        scale = CW / hours
        for i in range(0, hours + 1, tick_every):
            d.text(s, MX + i * scale - 0.4, y - 0.38, 0.8, 0.3, f"{i}h", size=11, color=MUTED, align=C)
        for (a, b, m, note, extra) in segs:
            fill, col = (EVENT if m == "EVENT" else MODE[m])
            x, w = MX + a * scale, (b - a) * scale
            d.box(s, x + 0.02, y, w - 0.04, h, fill=fill, paras=f"{MODE_NAME.get(m, '')}{extra}", size=14, bold=True, color=col,
                  align=C, anchor=MID, radius=0.15, margin=0.02)
            if labels and note:
                d.text(s, x + 0.05, y + h + 0.15, w - 0.1, label_h, note, size=14)

    s = d.slide("Scenario: a remote desert site visit",
                notes="The remote_site_visit scenario in the simulator, and the walkthrough persona in the dashboard.")
    timeline(s, 1.95, 8, [
        (0, 1, "ONLINE", "Depot: plan and mission pack copied to the device DB", ""),
        (1, 3, "LIMITED", "Highway and approach: edge model answers; cloud only in windows", ""),
        (3, 6, "OFFLINE", "On site, no coverage: edge model next to the compressor, plan from the mission pack, lockout and repair steps queued in the outbox", ""),
        (6, 7, "LIMITED", "Driving out: P0–P1 replay to the cloud DB", ""),
        (7, 8, "ONLINE", "Online: photo uploads, job complete", ""),
    ], label_h=2.0)
    d.box(s, MX, 4.75, CW, 1.0, fill=TINT, anchor=MID, size=16,
          paras=[{"runs": [("Outcome: ", {"bold": True}), ("the repair is done with no data loss; the cloud repair DB shows every step once the link returns.", {})]}])

    # 14 - PSPS + AI outage --------------------------------------------------
    s = d.slide("Scenarios: wildfire shutoff and cloud AI outage",
                notes="psps_outage and cloud_ai_outage are simulator scenarios.")
    d.text(s, MX, 1.45, CW, 0.4, "Public-safety power shutoff (24 h)", size=18, bold=True)
    timeline(s, 2.3, 24, [(0, 2, "ONLINE", "", ""), (2, 4, "LIMITED", "", ""), (4, 16, "OFFLINE", "", " + sensors lost: site power out"),
                          (16, 20, "LIMITED", "", ""), (20, 24, "ONLINE", "", "")], tick_every=4, labels=False, h=0.55)
    cols3 = [("Towers on backup", "Links degrade; diagnosis already at the edge"),
             ("Site dark", "Edge gone too: device model, guided inspection, van stock; everything queued"),
             ("Recovery", "Outbox replays to the cloud; ownership rules settle conflicts")]
    c3w = (CW - 2 * 0.3) / 3
    for i, (h, b) in enumerate(cols3):
        d.text(s, MX + i * (c3w + 0.3), 3.0, c3w, 1.1, [{"text": h, "bold": True, "size": 15}, {"text": b, "size": 14, "color": MUTED}], space_after=2)
    d.text(s, MX, 4.4, CW, 0.4, "Cloud AI outage (5 h)", size=18, bold=True)
    timeline(s, 5.25, 5, [(0, 1, "ONLINE", "", ""), (1, 3, "EVENT", "", "Online + cloud AI outage"), (3, 5, "ONLINE", "", "")], labels=False, h=0.55)
    d.text(s, MX, 5.95, CW, 0.9, [{"runs": [("Data stays live: ", {"bold": True}),
           ("reasoning moves to the edge model while the cloud database, ERP and dispatch keep working.", {"color": MUTED})]}], size=14)

    # 15 - Floor ----------------------------------------------------------
    s = d.slide("The floor: what always works at the compressor", notes="The guaranteed minimum, even Offline with sensors lost.")
    d.text(s, MX, 1.5, CW, 0.5, "Even Offline with sensors lost, a technician at the compressor can still:", size=18, color=MUTED)
    floor = [("Open the repair plan", "Steps, manuals, LOTO and past fixes from the mission pack DB"),
             ("Get guided diagnosis", "The device model ranks causes from what the technician observes"),
             ("Use van stock", "See what's in the van and record parts as they're used"),
             ("Record everything", "Steps, findings and photos queue in the outbox; nothing is lost")]
    fw, fg = (CW - 0.3) / 2, 0.3
    for i, (h, b) in enumerate(floor):
        x, y = MX + (i % 2) * (fw + fg), 2.3 + (i // 2) * 2.2
        d.box(s, x, y, fw, 1.95, fill=TINT)
        d.badge(s, x + 0.65, y + 0.975, 0.85, str(i + 1), fill=AMBER, size=22)
        d.text(s, x + 1.35, y + 0.25, fw - 1.6, 1.5, [{"text": h, "bold": True, "size": 19}, {"text": b, "size": 15, "color": MUTED}], anchor=MID, space_after=4)

    # 16 - Data and bandwidth ---------------------------------------------
    s = d.slide("Moving data over thin links", notes="Mission packs are the key offline mechanism; priority classes decide what goes first.")
    d.box(s, MX, 1.55, 5.2, 5.25, fill=TINT)
    d.text(s, MX + 0.3, 1.75, 4.6, 0.45, "Mission pack DB", size=19, bold=True)
    d.text(s, MX + 0.3, 2.25, 4.6, 0.6, "Copied to the device on assignment, and nightly on depot Wi-Fi", size=14, color=MUTED)
    d.text(s, MX + 0.3, 2.95, 4.6, 2.6, ["The repair plan from the cloud DB", "Manual sections and a local search index",
                                         "Past and similar repairs", "Likely parts", "Site access notes and hazards"], size=15, bullet=True, space_after=6)
    d.text(s, MX + 0.3, 5.65, 4.6, 1.0, [{"runs": [("At the edge: ", {"bold": True}), ("send features and alarms, not raw waveforms.", {"color": MUTED})]}], size=14)
    d.text(s, 6.2, 1.55, 6.5, 0.45, "Traffic priority classes", size=19, bold=True)
    pcls = [("P0", "Safety", "Trip alarms, LOTO confirmations", "Online, Limited (first)", "B83227", WHITE),
            ("P1", "Control", "Assignments, step updates", "Online, Limited", "D9732B", WHITE),
            ("P2", "Context", "Diagnosis, telemetry features", "Online, Limited", "F2C230", TEXT),
            ("P3", "Knowledge", "Mission-pack updates", "Online", TEAL, WHITE),
            ("P4", "Bulk", "Photos, video, raw waveforms", "Online (depot Wi-Fi)", MUTED, WHITE)]
    for i, (p, n, ex, allowed, fill, col) in enumerate(pcls):
        y = 2.15 + i * 0.93
        d.badge(s, 6.6, y + 0.4, 0.7, p, fill=fill, color=col, size=15)
        d.text(s, 7.1, y, 3.4, 0.85, [{"text": n, "bold": True, "size": 16}, {"text": ex, "size": 14, "color": MUTED}], anchor=MID)
        d.text(s, 10.65, y, 2.05, 0.85, allowed, size=14, bold=True, anchor=MID)

    # 17 - Sync -----------------------------------------------------------
    s = d.slide("Sync without conflicts: every record has an owner", notes="Ownership rules instead of generic merges.")
    owners = [("Cloud", "Assignments, reservations, repair plans"), ("Edge", "Telemetry and alarms"), ("Device", "On-site observations, parts used from the van")]
    ow = (CW - 2 * 0.3) / 3
    for i, (t, b) in enumerate(owners):
        fill, col = TIER[t]
        d.box(s, MX + i * (ow + 0.3), 1.6, ow, 1.55, fill=fill, color=col, anchor=MID, space_after=4,
              paras=[{"text": f"{t} owns", "bold": True, "size": 18}, {"text": b, "size": 15}])
    flow = ["Offline step done", "Stored as provisional", "Link returns", "Cloud DB applies once", "Supervisor sees it"]
    fx, fs = MX + 0.9, (CW - 1.8) / 4
    d.line(s, fx, 4.0, fx + 4 * fs, 4.0, color=TINT2, width=4)
    for i, f in enumerate(flow):
        cx = fx + i * fs
        d.badge(s, cx, 4.0, 0.6, str(i + 1), fill=TEAL, color=WHITE, size=16)
        d.text(s, cx - 1.05, 4.45, 2.1, 0.8, f, size=14, align=C)
    rules = [("Idempotency keys", "Replaying the outbox never applies a write twice"), ("Append-only data", "Findings, readings and photos never conflict"),
             ("Parts collision", "The earlier, higher-priority WO wins; the other gets an alternative source")]
    for i, (h, b) in enumerate(rules):
        d.box(s, MX + i * (ow + 0.3), 5.45, ow, 1.35, fill=TINT, space_after=3, paras=[{"text": h, "bold": True, "size": 16}, {"text": b, "size": 14, "color": MUTED}])

    # 18 - Safety and approvals -------------------------------------------
    s = d.slide("Safety and rule-based approvals", notes="The same deterministic rules run everywhere, offline included.")
    safety = [("Edge safety wins", "An 'unsafe to run' rule at the edge can't be overridden by any agent"),
              ("Read-only to equipment", "No control tools; setpoints stay with the controller's safety layer"),
              ("Staleness guardrails", "Old data is never shown as live; every request is logged")]
    for i, (h, b) in enumerate(safety):
        d.box(s, MX, 1.6 + i * 1.75, 4.3, 1.55, fill=TINT, space_after=4, paras=[{"text": h, "bold": True, "size": 17}, {"text": b, "size": 14, "color": MUTED}])
    appr = [["Action", "Condition", "Outcome"], ["Shutdown", "Edge safety rule fired", "Auto, supervisor notified"],
            ["Shutdown", "Any other case", "Site operator"], ["Dispatch", "Routine or soon, skills matched, on shift", "Auto"],
            ["Dispatch", "Urgent, missing skills or overtime", "Supervisor"], ["Parts", "Van or depot stock, under $1,000", "Auto"],
            ["Parts", "$1,000 or more, or vendor order", "Regional manager"], ["Workshop", "Any transfer to a workshop", "Supervisor"],
            ["Offline", "Would otherwise be auto", "Auto, provisional"]]
    d.table(s, 5.2, 1.6, [1.5, 4.0, 2.03], appr, row_h=0.575, size=14)

    # 19 - Demo decisions -------------------------------------------------
    s = d.slide("Demo scope: decisions made", notes="These answer the open questions from the design document, section 11.")
    dec = [("Cause ranking", "A trained model", "repair-rec-1.0: 9 KB, 94.5% top-1, runs in all three places"),
           ("Operating modes", "Online, Limited, Offline", "Cloud AI outage and sensors lost are events"),
           ("Places", "Cloud, Edge, Device", "Depot servers are part of the Edge"),
           ("Repair plans", "In a database", "Cloud DB, copied into the mission pack"),
           ("Approvals", "Rule-based", "Same rules everywhere, offline included"),
           ("Scale", "Under 50 of each", "30 compressors, 12 sites, 12 technicians")]
    tw, th = (CW - 2 * 0.3) / 3, 2.4
    for i, (q, a, e) in enumerate(dec):
        x, y = MX + (i % 3) * (tw + 0.3), 1.6 + (i // 3) * (th + 0.3)
        d.box(s, x, y, tw, th, fill=TINT)
        d.text(s, x + 0.25, y + 0.2, tw - 0.5, 0.35, q.upper(), size=12, bold=True, color=TEAL)
        d.text(s, x + 0.25, y + 0.6, tw - 0.5, 0.5, a, size=20, bold=True)
        d.text(s, x + 0.25, y + 1.2, tw - 0.5, 1.1, e, size=14, color=MUTED)

    # 20 - Roadmap --------------------------------------------------------
    s = d.slide("Roadmap and how we'll measure it", notes="Phase 1 is done; the demo dashboard shows the target behavior.")
    phases = ["Contracts and simulator", "Cloud MVP (Online)", "Device and mission packs", "Router and modes", "Edge pilot site", "Pilot, then scale"]
    px, ps = MX + 0.8, (CW - 1.6) / 5
    d.line(s, px, 2.3, px + 5 * ps, 2.3, color=TINT2, width=4)
    for i, ph in enumerate(phases):
        cx = px + i * ps
        fill, col, tag = (MODE["ONLINE"][0], WHITE, "DONE") if i == 0 else (AMBER, TEXT, "NEXT") if i == 1 else (TINT2, TEXT, "")
        d.badge(s, cx, 2.3, 0.75, str(i + 1), fill=fill, color=col, size=18)
        if tag:
            d.text(s, cx - 0.8, 1.45, 1.6, 0.35, tag, size=12, bold=True, align=C, color=MODE["ONLINE"][0] if i == 0 else "9A6B00")
        d.text(s, cx - 0.9, 2.85, 1.8, 1.0, ph, size=14, align=C, bold=i < 2)
    d.text(s, MX, 4.45, CW, 0.4, "Success metrics", size=18, bold=True)
    mets = ["Time to diagnose", "First-time fix rate", "Drive time per work order", "Parts-not-available rate", "Jobs done in Limited/Offline with no data loss"]
    mw = (CW - 4 * 0.25) / 5
    for i, m in enumerate(mets):
        d.box(s, MX + i * (mw + 0.25), 5.0, mw, 1.7, fill=TINT, paras=m, size=15, bold=True, anchor=MID, align=C)

    # 21 - Close ----------------------------------------------------------
    s = d.slide("What's running today", dark=True, title_size=40, title_box=(0.8, 0.8, 11.5, 0.9), notes="Close with what exists and the next step.")
    stats = [("4", "real processes in the live demo"), ("1", "AI agent: Claude + RAG over the manuals"), ("1", "trained model in all 3 places"), ("86", "tests passing")]
    sw4 = 11.7 / 4
    for i, (n, l) in enumerate(stats):
        x = 0.8 + i * sw4
        d.text(s, x, 2.0, sw4 - 0.3, 1.3, n, size=66, bold=True, color=AMBER)
        d.text(s, x, 3.3, sw4 - 0.3, 0.8, l, size=18, color=ON_DARK)
    d.text(s, 0.8, 4.6, 11.7, 0.5, "Next: real LLM agents on the same tools", size=24, bold=True, color=WHITE)
    d.text(s, 0.8, 5.2, 11.7, 1.5, ["Running now: MCP servers, device router, outbox and replay, and the manual agent (Claude Opus 5.5 + RAG)",
                                    "Next: more agents (orchestration, dispatch) on the same MCP tools",
                                    "Then: a pilot with real hardware: one depot, its edge gateways and tablets"],
           size=16, color=ON_DARK, bullet=True, space_after=6)

    d.save(out)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "docs" / "hybrid-ai-design.pptx"
    build(out)
    print(f"wrote {out}")
