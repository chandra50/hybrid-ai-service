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
from build_deck import (AMBER, CW, EVENT, INK, MODE, MODE_NAME, MUTED, MX, ON_DARK, ON_DARK_MUTED, SLATE, TEAL,  # noqa: E402
                        TEXT, TIER, TINT, TINT2, WHITE, Deck, rgb)

C, MID = PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE


def build(out: Path, static_motion: bool = False) -> None:
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
             ("6", "depots", "each with an edge server; 4 with workshops"),
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
    s = d.slide("Solution: agents move between three places",
                notes="Same MCP tools in the cloud, at the edge and on the device; a router decides where each "
                      "request runs; the repair plan lives in a database and travels with the technician.")
    tiers = [("Cloud", "Cloud", "Large model; repair recommendations DB, ERP, knowledge base"),
             ("Edge", "Edge (at the compressor)", "Edge model, safety rules; telemetry buffer, depot mirror"),
             ("Device", "Device (technician)", "Small model; mission pack DB, outbox, van stock")]
    for i, (t, label, desc) in enumerate(tiers):
        fill, col = TIER[t]
        y = 1.6 + i * 1.62
        d.box(s, MX, y, 5.4, 1.35, fill=fill, color=col, anchor=MID,
              paras=[{"text": label, "bold": True, "size": 18}, {"text": desc, "size": 14}])
        if i < 2:
            d.arrow(s, MX + 2.7, y + 1.37, MX + 2.7, y + 1.6, color=MUTED, width=1.5, dash=True, both=True)
    pts = [("A router picks where each request runs", "Cloud when Online, the edge model when the link is Limited or gone, the device when the edge is dark too."),
           ("Every answer is labeled", "Where it ran, why, how fresh it is, and what it cost in time and tokens."),
           ("A trained model and an AI agent", "A 9 KB model ranks causes in every place; a Claude agent searches the service manuals and writes cited repair steps (retrieval only when offline)."),
           ("Nothing is lost offline", "Updates queue in priority order and replay safely once, when the link returns.")]
    for i, (h, b) in enumerate(pts):
        y = 1.6 + i * 1.22
        d.badge(s, 6.75, y + 0.35, 0.55, str(i + 1), fill=AMBER, size=15)
        d.text(s, 7.2, y, 5.5, 1.1, [{"text": h, "bold": True, "size": 17}, {"text": b, "size": 14, "color": MUTED}],
               space_after=2)

    # Animated: agents moving between device, edge and cloud (click through in Slide Show)
    from build_agent_motion import add_motion_slide
    add_motion_slide(d, static=static_motion)

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
    gains = ["No guessing about data age: every answer says which place answered and when",
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
    journey = [("ONLINE", "Depot", "Plan copied into the mission pack DB; cloud model answers"),
               ("LIMITED", "Highway", "Weak signal: the edge model answers; cloud only in windows"),
               ("OFFLINE", "On site", "Live readings over the local link; lockout steps queued"),
               ("OFFLINE", "Repair", "Gateway dark: the device model takes over; plan continues"),
               ("OFFLINE", "Close out", "Test run, findings and photo go to the outbox"),
               ("LIMITED", "Driving out", "Safety records and job updates replay first"),
               ("ONLINE", "Back online", "Photo uploads; the cloud DB shows the job complete")]
    jx, js = MX + 0.75, (CW - 1.5) / 6
    d.line(s, jx, 2.95, jx + 6 * js, 2.95, color=TINT2, width=4)
    for i, (m, h, b) in enumerate(journey):
        cx = jx + i * js
        fill, col = MODE[m]
        d.text(s, cx - 0.8, 2.2, 1.6, 0.35, MODE_NAME[m].upper(), size=11, bold=True, color=MUTED, align=C)
        d.badge(s, cx, 2.95, 0.62, str(i + 1), fill=fill, color=col, size=15)
        d.text(s, cx - 0.85, 3.4, 1.7, 0.4, h, size=15, bold=True, align=C)
        d.text(s, cx - 0.85, 3.8, 1.7, 1.2, b, size=13, color=MUTED, align=C)
    d.box(s, MX, 5.2, CW, 1.3, fill=TINT, anchor=MID,
          paras=[{"runs": [("What's different: ", {"bold": True}),
                           ("the plan, manuals, past fixes, live readings and van stock are on the device. The assistant "
                            "still answers offline, and every step the technician ticks reaches the database later, "
                            "exactly once.", {})]}], size=16)

    # 7 - Hybrid modes -----------------------------------------------------------
    s = d.slide("When the network or the cloud fails",
                notes="Three modes for the technician's link, and two events that can happen in any mode. The "
                      "middle column says where the agents run.")
    rows = [["Mode or event", "Agents run on", "Supervisor sees", "Technician can still"],
            ["Online", "Cloud (+ edge for live data)", "Everything live", "Everything, with the large cloud model"],
            ["Limited", "Edge and device; cloud in windows", "Field updates arrive in bursts", "All work; photos wait for Online"],
            ["Offline", "Edge and device only", "Last known state, marked stale", "Plan, manuals, readings, lockout, outbox"],
            ["Cloud AI outage", "Edge model; cloud data stays live", "Live data, slower answers", "Same as normal, slower answers"],
            ["Sensors lost", "Device (edge is dark)", "No live data, clearly flagged", "Guided inspection instead of telemetry"]]
    fills = [MODE["ONLINE"], MODE["LIMITED"], MODE["OFFLINE"], EVENT, EVENT]
    d.table(s, MX, 1.55, [2.3, 3.2, 3.1, 3.5], rows, row_h=0.8, first_col_fills=fills, size=14)

    d.save(out)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--static"]
    out = Path(args[0]) if args else Path(__file__).resolve().parents[1] / "docs" / "hybrid-ai-brief.pptx"
    build(out, static_motion="--static" in sys.argv)   # --static: no animation (for PDF export)
    print(f"wrote {out}")
