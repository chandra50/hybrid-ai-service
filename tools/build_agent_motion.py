"""Build an animated slide showing agents moving between Device, Edge and Cloud.

    pip install python-pptx Pillow
    python tools/build_agent_motion.py            # docs/agent-movement.pptx + docs/agent-movement.gif

One slide, five clicks: Online -> Limited -> Offline -> Offline + sensors lost -> Online.
Agent chips move with standard motion-path animations (work in every PowerPoint
version); link and status overlays fade in and out. The GIF is rendered from the
same stage data, as a preview.
"""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_deck import (AMBER, EVENT, INK, MODE, MUTED, TEXT, TIER, TINT, TINT2, WHITE, Deck, H, W, rgb)  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"

# ---------------------------------------------------------------- stage data (shared by PPTX and GIF)
PLACES = ["Device", "Edge", "Cloud"]
AGENTS = [  # id, label, kind; order = slot priority inside a place (home agents first)
    ("field", "Field assistant", "agent"),
    ("sync", "Sync service", "service"),
    ("safety", "Safety rules", "rules"),
    ("orch", "Orchestrator", "agent"),
    ("rr", "Repair-rec model · 0 tokens", "ml"),
    ("dispatch", "Dispatch", "tool"),
    ("logistics", "Logistics (parts)", "tool"),
    ("assistant", "Assistant LLM", "llm"),
]
STAGES = [
    {"mode": "ONLINE", "banner": "1 · Online: the cloud is reachable, so agents and the model run in the cloud",
     "place": {"orch": "Cloud", "rr": "Cloud", "dispatch": "Cloud", "logistics": "Cloud", "assistant": "Cloud",
               "safety": "Edge", "field": "Device", "sync": "Device"}},
    {"mode": "LIMITED", "banner": "2 · Limited: weak, intermittent link, so work moves to the edge, next to the data",
     "place": {"orch": "Cloud", "rr": "Edge", "dispatch": "Edge", "logistics": "Edge", "assistant": "Edge",
               "safety": "Edge", "field": "Device", "sync": "Device"}},
    {"mode": "OFFLINE", "banner": "3 · Offline: no WAN, so the edge and the device carry on; dispatch is unavailable",
     "place": {"orch": "Device", "rr": "Edge", "dispatch": "Cloud", "logistics": "Device", "assistant": "Edge",
               "safety": "Edge", "field": "Device", "sync": "Device"}},
    {"mode": "OFFLINE", "event": True, "banner": "4 · Offline + sensors lost: the edge goes dark, so the device takes over",
     "place": {"orch": "Device", "rr": "Device", "dispatch": "Cloud", "logistics": "Device", "assistant": "Device",
               "safety": "Edge", "field": "Device", "sync": "Device"}},
    {"mode": "ONLINE", "banner": "5 · Back online: everything returns to the cloud and the outbox syncs",
     "place": {"orch": "Cloud", "rr": "Cloud", "dispatch": "Cloud", "logistics": "Cloud", "assistant": "Cloud",
               "safety": "Edge", "field": "Device", "sync": "Device"}},
]
# overlays: (id, first stage visible, first stage hidden again)
OVERLAYS = {"wan_limited": (1, 2), "wan_down": (2, 4), "cloud_dim": (2, 4), "edge_dark": (3, 4)}

# geometry (inches)
MX, ZGAP = 0.6, 0.55
ZW = (W - 2 * MX - 2 * ZGAP) / 3
ZY, ZH, HEAD = 2.15, 4.85, 0.75
CHIP_W, CHIP_H, ROW = ZW - 0.5, 0.44, 0.52
CHIP_Y0 = ZY + HEAD + 0.18
DBS = {"Device": "Mission pack DB · Outbox · Van stock · model copy",
       "Edge": "Telemetry buffer · Safety rules · Depot mirror · model copy",
       "Cloud": "Repair recs DB · Model registry · ERP · Knowledge base"}


def zone_x(place: str) -> float:
    return MX + PLACES.index(place) * (ZW + ZGAP)


def slot_positions(stage: dict) -> dict[str, tuple[float, float]]:
    pos, counts = {}, {p: 0 for p in PLACES}
    for aid, _, _ in AGENTS:
        p = stage["place"][aid]
        i = counts[p]
        counts[p] += 1
        pos[aid] = (zone_x(p) + (ZW - CHIP_W) / 2, CHIP_Y0 + i * ROW)
    return pos


CHIP_STYLE = {  # fill, text
    "agent": (INK, WHITE), "tool": ("4A6572", WHITE), "service": ("4A6572", WHITE),
    "rules": ("4A6572", WHITE), "llm": ("6B4FA0", WHITE), "ml": (AMBER, TEXT),
}


# ---------------------------------------------------------------- timing XML
class Timing:
    def __init__(self):
        self.n = 2
        self.clicks: list[list[str]] = []
        self.bld: set[tuple[int, int]] = set()

    def _id(self) -> int:
        self.n += 1
        return self.n

    def motion(self, spid: int, frm: tuple[float, float], to: tuple[float, float], first: bool) -> str:
        fx, fy, tx, ty = frm[0] / W, frm[1] / H, to[0] / W, to[1] / H
        path = f"M {fx:.4f} {fy:.4f} L {tx:.4f} {ty:.4f} E"
        a, b = self._id(), self._id()
        return (f'<p:par><p:cTn id="{a}" presetID="0" presetClass="path" presetSubtype="0" accel="50000" decel="50000" '
                f'fill="hold" nodeType="{"clickEffect" if first else "withEffect"}"><p:stCondLst><p:cond delay="0"/></p:stCondLst>'
                f'<p:childTnLst><p:animMotion origin="layout" path="{path}" pathEditMode="relative" ptsTypes="">'
                f'<p:cBhvr><p:cTn id="{b}" dur="1200" fill="hold"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
                f'<p:attrNameLst><p:attrName>ppt_x</p:attrName><p:attrName>ppt_y</p:attrName></p:attrNameLst></p:cBhvr>'
                f'</p:animMotion></p:childTnLst></p:cTn></p:par>')

    def fade(self, spid: int, entrance: bool, first: bool) -> str:
        grp = 0 if entrance else 1
        self.bld.add((spid, grp))
        a, b, c = self._id(), self._id(), self._id()
        node = "clickEffect" if first else "withEffect"
        if entrance:
            inner = (f'<p:set><p:cBhvr><p:cTn id="{b}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
                     f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName>'
                     f'</p:attrNameLst></p:cBhvr><p:to><p:strVal val="visible"/></p:to></p:set>'
                     f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{c}" dur="600"/>'
                     f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect>')
            cls, preset = "entr", 10
        else:
            inner = (f'<p:animEffect transition="out" filter="fade"><p:cBhvr><p:cTn id="{c}" dur="600"/>'
                     f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect>'
                     f'<p:set><p:cBhvr><p:cTn id="{b}" dur="1" fill="hold"><p:stCondLst><p:cond delay="599"/></p:stCondLst></p:cTn>'
                     f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName>'
                     f'</p:attrNameLst></p:cBhvr><p:to><p:strVal val="hidden"/></p:to></p:set>')
            cls, preset = "exit", 10
        return (f'<p:par><p:cTn id="{a}" presetID="{preset}" presetClass="{cls}" presetSubtype="0" fill="hold" grpId="{grp}" '
                f'nodeType="{node}"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>{inner}</p:childTnLst></p:cTn></p:par>')

    def xml(self) -> str:
        clicks = ""
        for effects in self.clicks:
            a, b = self._id(), self._id()
            clicks += (f'<p:par><p:cTn id="{a}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>'
                       f'<p:par><p:cTn id="{b}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
                       f'{"".join(effects)}</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>')
        bld = "".join(f'<p:bldP spid="{s}" grpId="{g}" animBg="1"/>' for s, g in sorted(self.bld))
        return (f'<p:timing xmlns:p="{P_NS}"><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
                f'<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>{clicks}'
                f'</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
                f'<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
                f'</p:childTnLst></p:cTn></p:par></p:tnLst><p:bldLst>{bld}</p:bldLst></p:timing>')


def set_alpha(shape, alpha_pct: int) -> None:
    clr = shape.fill._xPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
    etree.SubElement(clr, qn("a:alpha")).set("val", str(alpha_pct * 1000))


# ---------------------------------------------------------------- PPTX
def build_pptx(out: Path) -> None:
    d = Deck()
    add_motion_slide(d)
    d.save(out)


def add_motion_slide(d, static: bool = False) -> None:
    """Append the animated slide to an existing Deck (used by the design and brief decks too).

    static=True draws only the starting state (Online) with no animation, for PDF export.
    """
    s = d.slide("Where agents run as the network changes",
                notes="Click five times. 1 Online: orchestration, the repair-rec model, dispatch, logistics and the "
                      "assistant LLM run in the cloud; safety rules at the edge; the field assistant and sync on the "
                      "device. 2 Limited: the model, dispatch (roster snapshot), logistics (depot mirror) and the "
                      "assistant move to the edge, next to the data. 3 Offline: the WAN is down; the orchestrator and "
                      "logistics run reduced on the device, dispatch is unreachable. 4 Sensors lost: the edge goes "
                      "dark, so the model and the assistant run on the device from symptoms. 5 Online again: "
                      "everything returns to the cloud and the outbox syncs.")
    C, MID = PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE

    # zones
    for p in PLACES:
        x = zone_x(p)
        fill, col = TIER[p]
        d.box(s, x, ZY, ZW, ZH, fill=TINT, radius=0.05)
        d.box(s, x, ZY, ZW, HEAD, fill=fill, color=col, anchor=MID, radius=0.12,
              paras=[{"text": p, "bold": True, "size": 20},
                     {"text": {"Device": "technician tablet", "Edge": "site gateway + depot server", "Cloud": "authoritative"}[p], "size": 12}])
        d.text(s, x + 0.2, ZY + ZH - 0.62, ZW - 0.4, 0.55, [{"runs": [("Data: ", {"bold": True}), (DBS[p], {})]}], size=11, color=MUTED)

    # links: local device<->edge, WAN along the top
    y_link = ZY + HEAD / 2
    d.line(s, zone_x("Device") + ZW, y_link, zone_x("Edge"), y_link, color=MODE["ONLINE"][0], width=3)
    d.text(s, zone_x("Device") + ZW - 0.2, y_link - 0.42, ZGAP + 0.4, 0.3, "local", size=10, color=MUTED, align=C)
    d.line(s, zone_x("Edge") + ZW, y_link, zone_x("Cloud"), y_link, color=MODE["ONLINE"][0], width=3)
    d.text(s, zone_x("Edge") + ZW - 0.2, y_link - 0.42, ZGAP + 0.4, 0.3, "WAN", size=10, color=MUTED, align=C)
    wy = ZY - 0.22
    dc = (zone_x("Device") + ZW / 2, zone_x("Cloud") + ZW / 2)
    d.line(s, dc[0], ZY, dc[0], wy, color=MODE["ONLINE"][0], width=3)
    d.line(s, dc[0], wy, dc[1], wy, color=MODE["ONLINE"][0], width=3)
    d.line(s, dc[1], wy, dc[1], ZY, color=MODE["ONLINE"][0], width=3)

    overlay = {}
    def wan_overlay(color, label, dash):
        shapes = []
        for (x1, y1, x2, y2) in [(dc[0], ZY, dc[0], wy), (dc[0], wy, dc[1], wy), (dc[1], wy, dc[1], ZY),
                                 (zone_x("Edge") + ZW, y_link, zone_x("Cloud"), y_link)]:
            ln = d.line(s, x1, y1, x2, y2, color=color, width=3.5)
            etree.SubElement(ln.line._get_or_add_ln(), qn("a:prstDash")).set("val", dash)
            shapes.append(ln)
        shapes.append(d.chip(s, (dc[0] + dc[1]) / 2 - 1.1, wy - 0.2, 2.2, 0.38, label, color, WHITE if color != "F2C230" else TEXT, size=11))
        return shapes
    overlay["wan_limited"] = wan_overlay("C99A00", "WAN: in windows", "dash")
    overlay["wan_down"] = wan_overlay(MODE["OFFLINE"][0], "WAN down", "sysDot")

    # agent chips
    pos0 = slot_positions(STAGES[0])
    chips = {}
    for aid, label, kind in AGENTS:
        fill, col = CHIP_STYLE[kind]
        x, y = pos0[aid]
        sh = d.box(s, x, y, CHIP_W, CHIP_H, fill=fill, paras=label, size=14, bold=True, color=col, anchor=MID, align=C, radius=0.5)
        if kind == "ml":
            sh.adjustments[0] = 0.12
            sh.line.color.rgb = rgb(TEXT)
            sh.line.width = 12700
            etree.SubElement(sh.line._get_or_add_ln(), qn("a:prstDash")).set("val", "dash")
        sh.name = f"agent:{aid}"
        chips[aid] = sh

    # dimming overlays (above chips): cloud unreachable, edge dark
    cd = d.box(s, zone_x("Cloud"), ZY, ZW, ZH, fill="5B6B73", paras=[{"text": "Unreachable from the field", "bold": True, "size": 15}],
               color=WHITE, anchor=MSO_ANCHOR.BOTTOM, align=C, radius=0.05)
    set_alpha(cd, 55)
    cd.text_frame.margin_bottom = int(914400 * 0.75)
    ed = d.box(s, zone_x("Edge"), ZY, ZW, ZH, fill="14232B", paras=[{"text": "Edge dark: site power cut", "bold": True, "size": 15}],
               color=WHITE, anchor=MSO_ANCHOR.BOTTOM, align=C, radius=0.05)
    set_alpha(ed, 55)
    ed.text_frame.margin_bottom = int(914400 * 0.75)
    overlay["cloud_dim"], overlay["edge_dark"] = [cd], [ed]

    # banners (stacked; each later one fades in on top)
    banners = []
    for st in STAGES:
        fill, col = (EVENT if st.get("event") else MODE[st["mode"]])
        banners.append(d.box(s, MX, 1.28, W - 2 * MX, 0.56, fill=fill, paras=st["banner"], size=17, bold=True, color=col,
                             anchor=MID, radius=0.3, margin=0.25))
    d.text(s, MX, H - 0.5, 10, 0.3, ("Starting state (Online). The PowerPoint version animates all five stages."
                                     if static else "Click to step through the modes")
           + "  ·  square chip = trained model, purple = LLM, dark = agent, grey = tool/service", size=10, color=MUTED)

    if static:   # PDF: keep only the starting state, no hidden layers, no timing
        for sh in [x for shapes in overlay.values() for x in shapes] + banners[1:]:
            sh._element.getparent().remove(sh._element)
        return

    # timing: one click per stage after the first
    t = Timing()
    for k in range(1, len(STAGES)):
        effects, first = [], True
        prev, cur = slot_positions(STAGES[k - 1]), slot_positions(STAGES[k])
        effects.append(t.fade(banners[k].shape_id, True, first)); first = False
        for name, (on, off) in OVERLAYS.items():
            for sh in overlay[name]:
                if on == k:
                    effects.append(t.fade(sh.shape_id, True, False))
                if off == k:
                    effects.append(t.fade(sh.shape_id, False, False))
        for aid, _, _ in AGENTS:
            if prev[aid] != cur[aid]:
                (x0, y0), (x1, y1) = pos0[aid], pos0[aid]
                frm = (prev[aid][0] - x0, prev[aid][1] - y0)   # paths are relative to the shape's original position
                to = (cur[aid][0] - x1, cur[aid][1] - y1)
                effects.append(t.motion(chips[aid].shape_id, frm, to, False))
        t.clicks.append(effects)
    s._element.append(etree.fromstring(t.xml()))
    # <p:timing> must come before <p:extLst> if one exists
    ext = s._element.find(qn("p:extLst"))
    if ext is not None:
        s._element.remove(ext); s._element.append(ext)


# ---------------------------------------------------------------- GIF preview
def build_gif(out: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont
    S = 96  # px per inch -> 1280 x 720
    font_dir = Path("/usr/share/fonts/truetype/liberation")
    def F(size, bold=False):
        try:
            return ImageFont.truetype(str(font_dir / ("LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf")), size)
        except OSError:
            return ImageFont.load_default()
    hexc = lambda h: tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # noqa: E731
    px = lambda v: int(round(v * S))  # noqa: E731

    def frame(positions, k, alpha_overlays):
        im = Image.new("RGB", (px(W), px(H)), "white")
        dr = ImageDraw.Draw(im, "RGBA")
        dr.text((px(MX), px(0.42)), "Where agents run as the network changes", font=F(34, True), fill=hexc(TEXT))
        st = STAGES[k]
        bf, bc = (EVENT if st.get("event") else MODE[st["mode"]])
        dr.rounded_rectangle([px(MX), px(1.28), px(W - MX), px(1.84)], radius=26, fill=hexc(bf))
        dr.text((px(MX + 0.25), px(1.42)), st["banner"], font=F(21, True), fill=hexc(bc))
        y_link = ZY + HEAD / 2
        wy = ZY - 0.22
        dc = (zone_x("Device") + ZW / 2, zone_x("Cloud") + ZW / 2)
        wan = "C99A00" if alpha_overlays.get("wan_limited") else MODE["OFFLINE"][0] if alpha_overlays.get("wan_down") else MODE["ONLINE"][0]
        for (x1, y1, x2, y2) in [(dc[0], ZY, dc[0], wy), (dc[0], wy, dc[1], wy), (dc[1], wy, dc[1], ZY),
                                 (zone_x("Edge") + ZW, y_link, zone_x("Cloud"), y_link)]:
            dr.line([px(x1), px(y1), px(x2), px(y2)], fill=hexc(wan), width=4)
        local = MODE["OFFLINE"][0] if alpha_overlays.get("edge_dark") else MODE["ONLINE"][0]
        dr.line([px(zone_x("Device") + ZW), px(y_link), px(zone_x("Edge")), px(y_link)], fill=hexc(local), width=4)
        if alpha_overlays.get("wan_limited") or alpha_overlays.get("wan_down"):
            lab = "WAN: in windows" if alpha_overlays.get("wan_limited") else "WAN down"
            cx = px((dc[0] + dc[1]) / 2)
            dr.rounded_rectangle([cx - 105, px(wy) - 18, cx + 105, px(wy) + 18], radius=18, fill=hexc(wan))
            dr.text((cx, px(wy)), lab, font=F(15, True), fill=(255, 255, 255), anchor="mm")
        for p in PLACES:
            x = zone_x(p)
            fill, col = TIER[p]
            dr.rounded_rectangle([px(x), px(ZY), px(x + ZW), px(ZY + ZH)], radius=16, fill=hexc(TINT))
            dr.rounded_rectangle([px(x), px(ZY), px(x + ZW), px(ZY + HEAD)], radius=16, fill=hexc(fill))
            dr.text((px(x + 0.2), px(ZY + 0.12)), p, font=F(26, True), fill=hexc(col))
            dr.text((px(x + 0.2), px(ZY + 0.47)), {"Device": "technician tablet", "Edge": "site gateway + depot server", "Cloud": "authoritative"}[p], font=F(14), fill=hexc(col))
            dr.text((px(x + 0.2), px(ZY + ZH - 0.5)), "Data: " + DBS[p], font=F(12), fill=hexc(MUTED))
        for aid, label, kind in AGENTS:
            x, y = positions[aid]
            fill, col = CHIP_STYLE[kind]
            box = [px(x), px(y), px(x + CHIP_W), px(y + CHIP_H)]
            dr.rounded_rectangle(box, radius=6 if kind == "ml" else 21, fill=hexc(fill), outline=hexc(TEXT) if kind == "ml" else None, width=2)
            dr.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), label, font=F(17, True), fill=hexc(col), anchor="mm")
        for name, place, text in [("cloud_dim", "Cloud", "Unreachable from the field"), ("edge_dark", "Edge", "Edge dark: site power cut")]:
            a = alpha_overlays.get(name, 0)
            if a:
                x = zone_x(place)
                base = (91, 107, 115) if name == "cloud_dim" else (20, 35, 43)
                dr.rounded_rectangle([px(x), px(ZY), px(x + ZW), px(ZY + ZH)], radius=16, fill=base + (int(140 * a),))
                dr.text((px(x + ZW / 2), px(ZY + ZH - 0.95)), text, font=F(19, True), fill=(255, 255, 255, int(255 * a)), anchor="mm")
        return im

    def overlays_at(k):
        return {n: 1.0 for n, (on, off) in OVERLAYS.items() if on <= k < off}

    ease = lambda t: t * t * (3 - 2 * t)  # noqa: E731
    frames, durations = [], []
    for k in range(len(STAGES)):
        cur = slot_positions(STAGES[k])
        if k > 0:
            prev = slot_positions(STAGES[k - 1])
            for f in range(1, 13):
                t = ease(f / 12)
                pos = {a: (prev[a][0] + (cur[a][0] - prev[a][0]) * t, prev[a][1] + (cur[a][1] - prev[a][1]) * t) for a in cur}
                frames.append(frame(pos, k, overlays_at(k))); durations.append(70)
        frames.append(frame(cur, k, overlays_at(k))); durations.append(2200)
    frames = [f.convert("P", palette=Image.ADAPTIVE, colors=128) for f in frames]
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)


if __name__ == "__main__":
    build_pptx(ROOT / "docs" / "agent-movement.pptx")
    build_gif(ROOT / "docs" / "agent-movement.gif")
    print("wrote docs/agent-movement.pptx and docs/agent-movement.gif")
