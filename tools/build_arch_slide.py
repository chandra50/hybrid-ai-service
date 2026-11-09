"""The "Implementation architecture" slide, shared by the design deck and the brief deck.

    from build_arch_slide import add_arch_slide
    add_arch_slide(d)
"""

from __future__ import annotations

from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

from build_deck import CW, INK, MONO, MUTED, MX, ON_DARK, SLATE, TEXT, TIER, TINT, WHITE

C, MID = PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE

PLACES = [
    ("Device", ":8803", "technician laptop or tablet",
     ["Router: per-mode policy and deadlines", "Link monitor: probes decide the mode",
      "Mission pack and outbox (SQLite)", "Repair model and manual index copies", "Web page: live.html"]),
    ("Edge", ":8802", "depot server",
     ["MCP server: telemetry, diagnosis, parts", "Live telemetry files (JSONL)",
      "Repair model and manual index copies", "Pushes features to the cloud"]),
    ("Cloud", ":8801", "central services",
     ["MCP server: plans, parts, steps, outcomes", "Repair recommendations DB (SQLite)",
      "Manual agent: Claude Opus 5.5 + RAG", "Fleet, technicians, parts stock"]),
]

MODULES = [
    ("contracts", "JSON schemas for every message"),
    ("sim", "fleet, telemetry, network modes"),
    ("models", "repair model, 9 KB, no tokens"),
    ("rag", "BM25 index over the manuals"),
    ("agents", "the Claude manual agent"),
    ("live", "the four processes and netsim"),
    ("demo", "dashboard server and repair DB"),
]


def add_arch_slide(d):
    s = d.slide("Implementation architecture",
                notes="What actually runs. Four processes: the device router (:8803), the edge and cloud MCP servers "
                      "(:8802, :8801) and the network simulator (:8810-8813), a TCP proxy on every link. They speak "
                      "MCP over streamable HTTP with JSON results. Each place keeps its own data: SQLite on the cloud "
                      "and the device, telemetry files at the edge. The dashboard (:8765) is a separate, simulated "
                      "view. All of it is one Python package, src/hybrid_ai.")
    gap = 0.3
    pw = (CW - 2 * gap) / 3
    top = 1.45
    for i, (place, port, where, items) in enumerate(PLACES):
        x = MX + i * (pw + gap)
        fill, col = TIER[place]
        d.box(s, x, top, pw, 0.5, fill=fill, color=col, anchor=MID, margin=0.15,
              paras=[{"runs": [(f"{place}  {port}", {"bold": True, "size": 16}),
                               (f"   {where}", {"size": 12})]}])
        d.box(s, x, top + 0.55, pw, 1.6, fill=TINT, size=12, space_after=3,
              paras=[{"text": t, "bullet": True} for t in items])

    # the network simulator sits on every link between the places
    ny = top + 2.3
    d.box(s, MX, ny, CW, 0.55, fill=INK, color=ON_DARK, size=13, anchor=MID, align=C,
          paras=[{"runs": [("netsim  :8810-8813   ", {"bold": True, "color": WHITE}),
                           ("a TCP proxy on every link that delays, flaps or cuts it   ·   all calls: MCP over "
                            "streamable HTTP", {})]}])
    for i in range(2):
        x = MX + (i + 1) * (pw + gap) - gap / 2
        d.arrow(s, x - 0.13, top + 1.35, x + 0.13, top + 1.35, color=MUTED, width=1.5, both=True)

    # shared code and the things around it
    my = ny + 0.8
    d.text(s, MX, my, 8.0, 0.35, "One Python package: src/hybrid_ai/", size=13, bold=True)
    mw, mh = 1.9, 0.82
    for i, (mod, desc) in enumerate(MODULES):
        r, c = divmod(i, 4)
        x, y = MX + c * (mw + 0.12), my + 0.4 + r * (mh + 0.1)
        d.box(s, x, y, mw, mh, fill=WHITE, line="D5DFE2", margin=0.1, anchor=MID,
              paras=[{"text": mod, "bold": True, "size": 12, "font": MONO}, {"text": desc, "size": 10, "color": MUTED}])
    rx = MX + 4 * (mw + 0.12) + 0.15
    rw = MX + CW - rx
    side = [("Dashboard  :8765", "simulated supervisor and technician views, JSON API over the repair DB"),
            ("Deployment", "systemd user or system units · Ubuntu tarball · hosted copy on claude.ai"),
            ("Stack", "Python 3 · mcp 2.3 · uvicorn · SQLite · anthropic SDK · Leaflet")]
    for i, (h, b) in enumerate(side):
        y = my + i * 0.75
        d.box(s, rx, y, rw, 0.68, fill=TINT if i else "DCEFE3", margin=0.12, anchor=MID,
              paras=[{"text": h, "bold": True, "size": 12, "color": SLATE if i else TEXT}, {"text": b, "size": 10}])
    return s
