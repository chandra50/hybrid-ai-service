"""Build docs/hybrid-ai-brief.pptx: a concise deck (situation, challenges, solution)
told from the supervisor's and the repairing technician's points of view.

    pip install python-pptx
    python tools/build_brief_deck.py [output.pptx]
"""

from __future__ import annotations

import sys
from pathlib import Path

from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_deck import (AMBER, CW, INK, MODE, MODE_NAME, MUTED, MX, ON_DARK, ON_DARK_MUTED, SLATE, TEAL,  # noqa: E402
                        TEXT, TIER, TINT, TINT2, WHITE, Deck, rgb)

C, MID = PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE


def build(out: Path) -> None:
    d = Deck()

    # 1 - Title -----------------------------------------------------------
    s = d.slide("Keeping remote compressors running", dark=True, title_size=44, title_box=(0.8, 1.9, 11.5, 1.0),
                notes="A short brief: the situation, what makes it hard, and how hybrid AI agents help the "
                      "supervisor and the technician who repairs the compressor.")
    d.text(s, 0.8, 3.05, 11, 1.0, "Field service with hybrid AI agents, seen by the supervisor and by the technician "
           "who does the repair", size=24, color=ON_DARK)
    d.text(s, 0.8, 4.6, 11, 0.5, "hybrid-ai · November 2026", size=16, color=ON_DARK_MUTED)
    for i, (code, fill, col) in enumerate([("Supervisor", SLATE, WHITE), ("Technician", AMBER, TEXT)]):
        d.chip(s, 0.8 + i * 2.3, 5.4, 2.1, 0.5, code, fill, col, size=15)

    # 2 - Situation ---------------------------------------------------------
    s = d.slide("The situation: a spread-out compressor fleet",
                notes="Numbers are from the simulated demo fleet. Half of the compressors sit where coverage is "
                      "patchy or absent, and about one repair in five needed a second visit.")
    stats = [("30", "compressors", "industrial: screw, reciprocating, centrifugal, diesel, scroll"),
             ("12", "remote sites", "valley, desert and foothill locations"),
             ("6", "depots", "each a regional hub; 4 with workshops"),
             ("12", "technicians", "in service vans, different skills")]
    sw = (CW - 3 * 0.3) / 4
    for i, (n, l, sub) in enumerate(stats):
        x = MX + i * (sw + 0.3)
        d.box(s, x, 1.6, sw, 2.2, fill=TINT)
        d.text(s, x + 0.25, 1.75, sw - 0.5, 0.9, n, size=48, bold=True, color=TEAL)
        d.text(s, x + 0.25, 2.65, sw - 0.5, 0.4, l, size=16, bold=True)
        d.text(s, x + 0.25, 3.05, sw - 0.5, 0.7, sub, size=13, color=MUTED)
    d.text(s, MX, 4.2, CW, 0.45, "Every fault starts the same chain of decisions", size=20, bold=True)
    chain = ["What's wrong?", "Who goes?", "On site or workshop?", "Are the parts in the van?", "How do I fix it?", "Record it"]
    cw = (CW - 5 * 0.25) / 6
    for i, c in enumerate(chain):
        x = MX + i * (cw + 0.25)
        d.box(s, x, 4.8, cw, 0.95, fill=WHITE, line=TINT2, paras=c, size=15, bold=True, align=C, anchor=MID)
        if i < 5:
            d.arrow(s, x + cw + 0.02, 5.275, x + cw + 0.23, 5.275, color=MUTED, width=1.5)
    d.box(s, MX, 6.05, CW, 0.75, fill="FDEEC2", anchor=MID,
          paras=[{"runs": [("The problem: ", {"bold": True}),
                           ("half the compressors are at sites with patchy or no coverage, and about 1 in 5 past "
                            "repairs needed a return visit.", {})]}], size=16)

    # 3 - Challenges --------------------------------------------------------
    s = d.slide("The challenges",
                notes="These are the conditions any solution has to survive. A cloud-only assistant fails "
                      "exactly when the technician needs it most.")
    ch = [("No signal where the work is", "Dead zones and wildfire power shutoffs cut the link for hours or days."),
          ("Live data is heavy", "Vibration, temperature and pressure can't all stream over one bar of LTE."),
          ("Knowledge is scattered", "Manuals, past repairs and part lists live in different places."),
          ("The cloud AI can fail too", "Model outages happen even when the network is fine."),
          ("Safety can't wait", "Lockout, shutdowns and approvals must work offline and never use stale data."),
          ("Updates get lost", "Notes taken offline are retyped later, or never reach the office.")]
    cw3, ch_h = (CW - 2 * 0.3) / 3, 2.4
    for i, (h, b) in enumerate(ch):
        col, row = i % 3, i // 3
        x, y = MX + col * (cw3 + 0.3), 1.6 + row * (ch_h + 0.3)
        d.box(s, x, y, cw3, ch_h, fill=TINT)
        d.badge(s, x + 0.55, y + 0.6, 0.62, str(i + 1), fill=AMBER, size=16)
        d.text(s, x + 0.25, y + 1.05, cw3 - 0.5, 0.45, h, size=17, bold=True)
        d.text(s, x + 0.25, y + 1.5, cw3 - 0.5, 0.85, b, size=14, color=MUTED)

    # 4 - Solution -----------------------------------------------------------
    s = d.slide("The solution: agents that work at every tier",
                notes="Same MCP tools at every tier; a router decides where each request runs; the repair plan "
                      "lives in a database and travels with the technician.")
    tiers = [("Cloud", "Large model, full history, live ERP and dispatch"), ("Hub", "Depot model and regional copies"),
             ("Field", "Device model, mission pack, outbox"), ("Edge", "Site gateway: live readings and safety rules")]
    for i, (t, desc) in enumerate(tiers):
        fill, col = TIER[t]
        y = 1.6 + i * 1.22
        d.box(s, MX, y, 5.4, 1.0, fill=fill, color=col, anchor=MID,
              paras=[{"text": {"Field": "Device (technician)", "Edge": "Edge (at the compressor)"}.get(t, t), "bold": True, "size": 17},
                     {"text": desc, "size": 14}])
        if i < 3:
            d.arrow(s, MX + 2.7, y + 1.02, MX + 2.7, y + 1.2, color=MUTED, width=1.5, dash=True, both=True)
    pts = [("A router picks where each request runs", "Cloud when it can, hub or device when it can't, based on the live network mode."),
           ("Every answer is labeled", "Where it ran, why, how fresh it is, and what it cost in time and tokens."),
           ("Repair plans live in a database", "Ranked causes, step-by-step plan, parts and references, synced into the technician's mission pack."),
           ("Nothing is lost offline", "Updates queue in priority order and replay safely once, when the link returns.")]
    for i, (h, b) in enumerate(pts):
        y = 1.6 + i * 1.22
        d.badge(s, 6.75, y + 0.35, 0.55, str(i + 1), fill=AMBER, size=15)
        d.text(s, 7.2, y, 5.5, 1.1, [{"text": h, "bold": True, "size": 17}, {"text": b, "size": 14, "color": MUTED}],
               space_after=2)

    # 5 - Supervisor -----------------------------------------------------------
    s = d.slide("Supervisor's view: decide fast, see everything",
                notes="The supervisor works from the office, always online. What changes with the field's network "
                      "is how fresh the field data is and when technician updates arrive.")
    d.chip(s, MX, 1.55, 1.7, 0.42, "Supervisor", SLATE, WHITE, size=13)
    flow = [("Review", "Each work order arrives with a ranked diagnosis, best technicians, repair location and parts."),
            ("Approve", "Rules approve routine work; urgent dispatch and parts over $1,000 come to the supervisor."),
            ("Track", "A live panel shows every request: where it ran, why, and the time and tokens it cost."),
            ("Close", "Field updates appear as they sync; the repair outcome lands in the database.")]
    fw = (CW - 3 * 0.35) / 4
    for i, (h, b) in enumerate(flow):
        x = MX + i * (fw + 0.35)
        d.box(s, x, 2.3, fw, 2.5, fill=TINT)
        d.badge(s, x + 0.55, 2.85, 0.62, str(i + 1), fill=SLATE, color=WHITE, size=16)
        d.text(s, x + 0.25, 3.3, fw - 0.5, 0.45, h, size=19, bold=True)
        d.text(s, x + 0.25, 3.75, fw - 0.5, 1.0, b, size=14, color=MUTED)
        if i < 3:
            d.arrow(s, x + fw + 0.03, 3.55, x + fw + 0.32, 3.55, color=MUTED, width=1.5)
    d.text(s, MX, 5.15, CW, 0.4, "What's different", size=18, bold=True)
    gains = ["No guessing about data age: every answer says which tier answered and when",
             "Approvals by rule, so only the decisions that need a person reach one",
             "Knows exactly which technician updates are still in transit"]
    gw = (CW - 2 * 0.3) / 3
    for i, g in enumerate(gains):
        d.box(s, MX + i * (gw + 0.3), 5.6, gw, 1.15, fill=WHITE, line=TINT2, paras=g, size=14, anchor=MID)

    # 6 - Technician -----------------------------------------------------------
    s = d.slide("Technician's view: one repair, through a dead zone",
                notes="This is the walkthrough persona in the dashboard. The technician follows the repair plan "
                      "from the database; the network changes underneath, the work does not stop.")
    d.chip(s, MX, 1.55, 1.7, 0.42, "Technician", AMBER, TEXT, size=13)
    journey = [("M0", "Depot", "Plan and mission pack sync; asks what's wrong"),
               ("M1", "Highway", "Checks parts; a missing one is reserved at the depot"),
               ("M2", "Approach", "Device answers first; cloud only when a window opens"),
               ("M5", "On site", "Live readings over the local link; lockout steps logged"),
               ("M5", "Repair", "Verify, repair and test-run from the plan, fully offline"),
               ("M5", "Close out", "Findings, parts used and photo go to the outbox"),
               ("M2", "Driving out", "Safety records and job updates send first"),
               ("M0", "Back online", "Photo uploads; the database shows the job complete")]
    jx, js = MX + 0.65, (CW - 1.3) / 7
    d.line(s, jx, 2.75, jx + 7 * js, 2.75, color=TINT2, width=4)
    for i, (m, h, b) in enumerate(journey):
        cx = jx + i * js
        fill, col = MODE[m]
        d.badge(s, cx, 2.75, 0.62, m, fill=fill, color=col, size=13)
        d.text(s, cx - 0.72, 3.2, 1.44, 0.4, h, size=15, bold=True, align=C)
        d.text(s, cx - 0.72, 3.6, 1.44, 1.5, b, size=13, color=MUTED, align=C)
    d.box(s, MX, 5.05, CW, 1.3, fill=TINT, anchor=MID,
          paras=[{"runs": [("What's different: ", {"bold": True}),
                           ("the plan, manuals, past fixes, live readings and van stock are on the device. The assistant "
                            "still answers offline, and every step the technician ticks reaches the database later, "
                            "exactly once.", {})]}], size=16)

    # 7 - Hybrid modes -----------------------------------------------------------
    s = d.slide("When the network or the cloud fails",
                notes="Each row is a network mode from the design. The supervisor column is what the office sees; "
                      "the technician column is what still works in the field.")
    rows = [["Mode", "Supervisor sees", "Technician can still"],
            ["M0  Connected", "Everything live", "Everything, with the large cloud model"],
            ["M1  Constrained", "Live, slower updates", "All work; photos wait for a better link"],
            ["M2  Intermittent", "Field updates arrive in bursts", "Device answers first; updates queue"],
            ["M3  Cloud AI down", "Live data; hub model answers", "Same as normal, slower answers"],
            ["M4  Hub island", "Updates held at the depot hub", "Hub answers; depot stock is live"],
            ["M5  Fully offline", "Last known state, marked stale", "Plan, manuals, readings, lockout, outbox"],
            ["M6  Sensors lost", "No live data, clearly flagged", "Guided inspection instead of telemetry"]]
    fills = [MODE[f"M{i}"] for i in range(7)]
    d.table(s, MX, 1.55, [2.9, 4.35, 4.85], rows, row_h=0.62, first_col_fills=fills, size=14)

    # 8 - Proof and next steps ----------------------------------------------------
    s = d.slide("What the demo shows, and what's next", dark=True, title_size=36, title_box=(0.8, 0.7, 11.5, 0.9),
                notes="Figures are from one walkthrough run in the dashboard; timings vary a little per run "
                      "because the network model has randomness.")
    proof = [("50+", "requests in one repair, each logged"), ("~45%", "answered without the cloud"),
             ("12 / 12", "repair steps reached the database"), ("0", "updates lost offline")]
    pw = 11.7 / 4
    for i, (n, l) in enumerate(proof):
        x = 0.8 + i * pw
        d.text(s, x, 1.9, pw - 0.3, 1.1, n, size=54, bold=True, color=AMBER)
        d.text(s, x, 3.0, pw - 0.3, 0.8, l, size=17, color=ON_DARK)
    d.text(s, 0.8, 4.35, 11.7, 0.5, "Next steps", size=22, bold=True, color=WHITE)
    d.text(s, 0.8, 4.95, 11.7, 1.8,
           ["Replace the rule-based plans with real MCP agents on the same tools and database",
            "Pilot with one depot's technicians and a handful of compressors",
            "Measure time to diagnose, first-time fix rate and return visits"],
           size=17, color=ON_DARK, bullet=True, space_after=8)

    d.save(out)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "docs" / "hybrid-ai-brief.pptx"
    build(out)
    print(f"wrote {out}")
