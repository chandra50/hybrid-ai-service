/* hybrid-ai Field Ops demo dashboard.
 * Data comes from data.js (window.HYBRID_DATA), built by `python -m hybrid_ai.demo.build_data`.
 * All "network" behavior is simulated in the page, following docs/DESIGN.md section 5.
 */
(() => {
  "use strict";
  const D = window.HYBRID_DATA;
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ------------------------------------------------------------------ mode model (DESIGN.md §5)
  const MODES = {
    M0: { name: "Connected", color: "var(--m0)", dark: false, desc: "Full cloud reasoning, live data",
          links: { cloud: "up", hub: "up", edgeCloud: "up", llm: "up" }, tel: 30 },
    M1: { name: "Constrained", color: "var(--m1)", dark: true, desc: "Slow link: compact context, media deferred",
          links: { cloud: "slow", hub: "slow", edgeCloud: "slow", llm: "up" }, tel: 240 },
    M2: { name: "Intermittent", color: "var(--m2)", dark: true, desc: "Link drops: local first, writes provisional",
          links: { cloud: "flaky", hub: "flaky", edgeCloud: "flaky", llm: "up" }, tel: 900 },
    M3: { name: "Cloud AI down", color: "var(--m3)", dark: false, desc: "Network fine, model API failing",
          links: { cloud: "up", hub: "up", edgeCloud: "up", llm: "down" }, tel: 30 },
    M4: { name: "Hub island", color: "var(--m4)", dark: false, desc: "WAN down, depot hub reachable",
          links: { cloud: "down", hub: "up", edgeCloud: "down", llm: "down" }, tel: null },
    M5: { name: "Fully offline", color: "var(--m5)", dark: false, desc: "Only the device and the site gateway",
          links: { cloud: "down", hub: "down", edgeCloud: "down", llm: "down" }, tel: null },
  };
  // Who answers each workflow in each mode: [tier, confidence, how]
  const WF = {
    W1: { M0: ["cloud", "confirmed", "Cloud model, full fleet history"], M1: ["cloud", "confirmed", "Cloud model, compact edge features"],
          M2: ["field", "provisional", "Device model first; cloud second opinion when the link is up"], M3: ["hub", "provisional", "Hub model over live cloud data"],
          M4: ["hub", "provisional", "Hub model + regional knowledge"], M5: ["field", "provisional", "Edge rules + device model + mission pack"] },
    W2: { M0: ["cloud", "confirmed", "Live optimizer"], M1: ["cloud", "confirmed", "Live optimizer, small payloads"],
          M2: ["hub", "provisional", "Hub roster snapshot (cloud unreachable in deadline)"], M3: ["cloud", "confirmed", "Deterministic optimizer, no LLM needed"],
          M4: ["hub", "provisional", "Hub roster snapshot + rules"], M5: ["none", "unavailable", "Not available offline: call the dispatcher"] },
    W3: { M0: ["cloud", "confirmed", "Learned + rule score"], M1: ["cloud", "confirmed", "Learned + rule score"],
          M2: ["field", "provisional", "Rule score, computed locally"], M3: ["cloud", "confirmed", "Rule score"],
          M4: ["hub", "provisional", "Rule score"], M5: ["field", "provisional", "Rule score; technician decides"] },
    W4: { M0: ["cloud", "confirmed", "Live ERP, hard reservation"], M1: ["cloud", "confirmed", "Live ERP, hard reservation"],
          M2: ["field", "provisional", "Soft reservation, confirmed on sync"], M3: ["cloud", "confirmed", "Live ERP (data still up)"],
          M4: ["hub", "provisional", "Depot stock live, others from snapshot"], M5: ["field", "provisional", "Truck stock only"] },
  };
  const TIER_NAME = { cloud: "Cloud", hub: "Hub", field: "Device", edge: "Edge", none: "Unavailable" };
  const PRIO_LABEL = { P0: "Safety", P1: "Control", P2: "Context", P3: "Knowledge", P4: "Bulk" };

  // ------------------------------------------------------------------ state
  const byId = (arr, key) => Object.fromEntries(arr.map((x) => [x[key], x]));
  const ASSETS = byId(D.assets, "asset_id");
  const TECHS = byId(D.technicians, "technician_id");
  const DEPOTS = byId(D.depots, "depot_id");
  const WOS = byId(D.work_orders, "work_order_id");
  const NOW0 = new Date(D.generated.now).getTime();

  const firstAssigned = D.work_orders.find((w) => w.assigned_technician_id);
  const state = {
    persona: "supervisor",
    mode: "M0",
    sensorsLost: false,
    simOffset: 0,               // seconds since NOW0
    offlineSince: null,         // sim seconds when cloud became unreachable
    selectedWO: D.work_orders[0]?.work_order_id,
    techId: firstAssigned?.assigned_technician_id || D.technicians[0].technician_id,
    techTab: "diagnose",
    queue: [],                  // {id, dir:'up'|'down', prio, wo, text, kind, payload, status, created}
    feed: {},                   // wo -> [{t, text}] as seen by the cloud
    techView: {},               // wo -> {status, assigned} as seen by the device
    checklist: {},              // wo -> Set(step idx)
    truck: Object.fromEntries(D.technicians.map((t) => [t.technician_id, Object.fromEntries(t.truck_stock.map((p) => [p.part_number, p.qty]))])),
    inspection: {},             // wo -> Set(symptom) for M6 guided inspection
    scenario: null, playing: false, timer: null,
  };
  for (const w of D.work_orders) {
    state.feed[w.work_order_id] = [{ t: 0, text: w.source === "telemetry" ? "Created from telemetry alarm" : "Reported by site operator" }];
    if (w.assigned_technician_id) state.techView[w.work_order_id] = { status: w.status, assigned: w.assigned_technician_id };
  }
  let seq = 0;

  // ------------------------------------------------------------------ helpers
  const simNow = () => NOW0 + state.simOffset * 1000;
  const fmtTime = (ms) => new Date(ms).toISOString().replace("T", " ").slice(0, 16) + " UTC";
  const fmtAge = (s) => (s == null ? "no data" : s < 60 ? `${Math.round(s)} s old` : s < 3600 ? `${Math.round(s / 60)} min old` : `${(s / 3600).toFixed(1)} h old`);
  const usd = (n) => "$" + n.toLocaleString("en-US");
  const mode = () => MODES[state.mode];
  const cloudReachable = () => ["up", "slow"].includes(mode().links.cloud) || (mode().links.cloud === "flaky" && Math.random() < 0.45);
  const hubReachable = () => ["up", "slow"].includes(mode().links.hub) || (mode().links.hub === "flaky" && Math.random() < 0.5);
  const offlineAge = () => (state.offlineSince == null ? null : Math.max(0, state.simOffset - state.offlineSince) + 1800);

  function prov(wf) {
    const [tier, conf, how] = WF[wf][state.mode];
    let age = 0;
    if (tier === "hub") age = state.mode === "M3" ? 5 : 3 * 3600;
    if (tier === "field") age = offlineAge() ?? 600;
    const ageTxt = tier === "none" ? "" : ` · ${fmtAge(age)}`;
    return { tier, conf, how, html: `<span class="prov ${tier}" title="${esc(how)}">${TIER_NAME[tier]} <span class="conf">· ${conf}${ageTxt}</span></span>` };
  }

  function telemetryAgeForSupervisor() {
    if (state.sensorsLost) return null;
    const t = mode().tel;
    return t == null ? offlineAge() : t;
  }

  let toastTimer;
  function toast(msg) {
    const el = $("#toast") || Object.assign(document.body.appendChild(document.createElement("div")), { id: "toast", className: "toast" });
    el.textContent = msg; el.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
  }

  // ------------------------------------------------------------------ queue / sync
  function enqueue(dir, prio, wo, text, kind, payload = {}) {
    state.queue.push({ id: ++seq, dir, prio, wo, text, kind, payload, status: "queued", created: state.simOffset });
    syncTick(true);
  }
  function allowed(prio) {
    switch (state.mode) {
      case "M0": case "M3": return true;
      case "M1": return prio !== "P4";            // media deferred
      case "M2": return ["P0", "P1", "P2"].includes(prio);
      case "M4": return ["P0", "P1", "P2"].includes(prio); // to the hub only
      default: return false;
    }
  }
  function syncTick(immediate = false) {
    let changed = false;
    for (const q of state.queue) {
      if (q.status === "synced") continue;
      if (!allowed(q.prio)) continue;
      if (state.mode === "M4") {
        if (q.dir === "up" && q.status === "queued" && hubReachable()) { q.status = "hub"; changed = true; }
        continue;
      }
      if (!cloudReachable()) continue;
      if (immediate && state.mode === "M2") continue; // intermittent: wait for a window
      q.status = "synced"; changed = true;
      apply(q);
    }
    if (changed) render();
  }
  function apply(q) {
    if (q.dir === "up") {
      state.feed[q.wo] = state.feed[q.wo] || [];
      state.feed[q.wo].push({ t: state.simOffset, text: q.text });
      if (q.kind === "status") WOS[q.wo].status = q.payload.status;
      if (q.kind === "complete") { WOS[q.wo].status = "completed"; ASSETS[WOS[q.wo].asset_id].status = "healthy"; }
    } else if (q.kind === "assign") {
      state.techView[q.wo] = { status: "assigned", assigned: q.payload.tech };
    }
  }

  // ------------------------------------------------------------------ map
  const map = L.map("map", { zoomControl: true, preferCanvas: false }).setView([36.8, -119.4], 6);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  const STATUS_COLOR = { healthy: "#2e8b57", warning: "#e0a100", fault: "#b83227" };
  const assetLayer = L.layerGroup().addTo(map);
  const depotLayer = L.layerGroup().addTo(map);
  const techLayer = L.layerGroup().addTo(map);
  const routeLayer = L.layerGroup().addTo(map);

  function assetPopup(a) {
    const wo = a.work_order_id ? `<br><a href="#" data-open-wo="${a.work_order_id}">${a.work_order_id}</a>` : "";
    return `<b>${esc(a.asset_id)}</b> · ${esc(a.model)}<br>${esc(a.category)}<br>${esc(a.site_name)} (${esc(a.region)})<br>
      Coverage: <b>${esc(a.coverage)}</b> · Status: <b style="color:${STATUS_COLOR[a.status]}">${a.status}</b>${wo}`;
  }
  function drawMap() {
    assetLayer.clearLayers(); depotLayer.clearLayers(); techLayer.clearLayers(); routeLayer.clearLayers();
    const job = state.persona === "technician" ? myJobs()[0] : null;
    for (const d of D.depots) {
      L.marker([d.lat, d.lon], {
        icon: L.divIcon({ className: "", html: `<div class="depot-icon" style="width:26px;height:20px">${d.has_workshop ? "WS" : "HUB"}</div>`, iconSize: [26, 20] }),
        title: `${d.city} depot`,
      }).bindPopup(`<b>${esc(d.city)} depot</b> (${esc(d.depot_id)})<br>Regional hub${d.has_workshop ? " + workshop" : ""}`).addTo(depotLayer);
    }
    for (const a of D.assets) {
      const highlight = (state.persona === "supervisor" && a.work_order_id === state.selectedWO) || (job && job.asset_id === a.asset_id);
      L.circleMarker([a.lat, a.lon], {
        radius: highlight ? 11 : a.status === "healthy" ? 6 : 8, color: highlight ? "#14232b" : "#ffffff", weight: highlight ? 3 : 2,
        fillColor: STATUS_COLOR[a.status], fillOpacity: 0.95,
      }).bindPopup(assetPopup(a)).addTo(assetLayer);
    }
    const techs = state.persona === "technician" ? [TECHS[state.techId]] : D.technicians.filter((t) => t.on_shift);
    for (const t of techs) {
      const ini = t.name.split(" ").map((p) => p[0]).join("");
      const me = state.persona === "technician";
      L.marker([t.lat, t.lon], {
        icon: L.divIcon({ className: "", html: `<div class="tech-icon ${me ? "me" : ""}" style="width:24px;height:24px">${esc(ini)}</div>`, iconSize: [24, 24] }),
        title: t.name,
      }).bindPopup(`<b>${esc(t.name)}</b> (${esc(t.technician_id)})<br>Truck ${esc(t.truck_id)} · ${esc(t.skills.join(", "))}`).addTo(techLayer);
    }
    if (job) {
      const a = ASSETS[job.asset_id], t = TECHS[state.techId];
      L.polyline([[t.lat, t.lon], [a.lat, a.lon]], { color: "#14232b", weight: 3, dashArray: "6 6" }).addTo(routeLayer);
    }
  }
  map.on("popupopen", (e) => {
    const link = e.popup.getElement().querySelector("[data-open-wo]");
    if (link) link.addEventListener("click", (ev) => { ev.preventDefault(); setPersona("supervisor"); state.selectedWO = link.dataset.openWo; render(); });
  });
  function focusMap() {
    if (state.persona === "technician") {
      const job = myJobs()[0]; const t = TECHS[state.techId];
      const pts = [[t.lat, t.lon]]; if (job) pts.push([ASSETS[job.asset_id].lat, ASSETS[job.asset_id].lon]);
      map.fitBounds(L.latLngBounds(pts).pad(0.6), { maxZoom: 10 });
    } else if (state.selectedWO) {
      const a = ASSETS[WOS[state.selectedWO].asset_id];
      map.setView([a.lat, a.lon], Math.max(map.getZoom(), 7), { animate: true });
    }
  }

  // ------------------------------------------------------------------ shared widgets
  function spark(sig, series, th, stale) {
    const pts = series.points.map((p) => p.value);
    const W = 400, H = 56, pad = 4;
    const lines = [th.warn, th.trip].filter((v) => v != null);
    const lo = Math.min(...pts, ...lines), hi = Math.max(...pts, ...lines);
    const y = (v) => H - pad - ((v - lo) / (hi - lo || 1)) * (H - 2 * pad);
    const x = (i) => pad + (i / (pts.length - 1)) * (W - 2 * pad);
    const path = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const guide = (v, c) => (v == null ? "" : `<line x1="0" x2="${W}" y1="${y(v)}" y2="${y(v)}" stroke="${c}" stroke-dasharray="4 4" stroke-width="1.5"/>`);
    const last = pts[pts.length - 1];
    const breach = th.low_is_bad ? (th.warn != null && last <= th.warn) : (th.warn != null && last >= th.warn);
    return `<div class="sig"><div class="row"><b>${esc(sig)}</b><span class="${breach ? "bad" : "muted"}">${last} ${esc(series.unit)}${th.warn != null ? ` · warn ${th.low_is_bad ? "<" : ">"} ${th.warn}` : ""}</span></div>
      <svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(sig)} trend">
        ${guide(th.warn, "#e0a100")}${guide(th.trip, "#b83227")}
        <path d="${path}" fill="none" stroke="${stale ? "#93a7b0" : "#1b8a8f"}" stroke-width="2"/></svg></div>`;
  }
  function telemetryBlock(assetId, ageS, lostMsg) {
    const T = D.telemetry[assetId];
    if (ageS === null) return `<div class="note">${lostMsg}</div>`;
    const stale = ageS > 600;
    const al = T.alarms.slice(-3).map((a) => `<div><span class="pill ${a.severity === "critical" ? "pri-urgent" : "pri-soon"}">${esc(a.code)}</span> <span class="muted">${esc(a.ts.slice(11, 16))}</span></div>`).join("");
    return `${stale ? `<div class="note">Last known values, ${fmtAge(ageS)}. The edge-to-cloud link is down.</div>` : ""}
      ${T.series.map((s) => spark(s.signal, s, T.thresholds[s.signal], stale)).join("")}
      ${al ? `<div class="sub" style="margin-top:4px">Recent alarms</div>${al}` : ""}`;
  }
  function causesBlock(diag) {
    return diag.causes.map((c) => `<div class="cause"><span>${esc(c.description)} <span class="muted">${esc(c.cause_code)}</span></span>
      <div class="bar"><span style="width:${Math.round(c.probability * 100)}%"></span></div><b>${Math.round(c.probability * 100)}%</b></div>`).join("");
  }

  // ------------------------------------------------------------------ supervisor
  function kpis() {
    const open = D.work_orders.filter((w) => w.status !== "completed");
    const pending = D.work_orders.reduce((n, w) => n + w.approvals.filter((a) => a.outcome === "human").length, 0);
    const faults = D.assets.filter((a) => a.status !== "healthy").length;
    const queued = state.queue.filter((q) => q.dir === "up" && q.status !== "synced").length;
    const tiles = state.persona === "supervisor"
      ? [[D.assets.length, "Assets"], [faults, "Need attention", faults > 0], [open.length, "Open work orders"],
         [pending, "Approvals waiting", pending > 0], [queued, "Field updates in transit", queued > 0]]
      : [[myJobs().length, "My jobs"], [Object.values(state.truck[state.techId]).reduce((a, b) => a + b, 0), "Parts on truck"],
         [queued, "Outbox (not yet synced)", queued > 0], [state.mode, "Network mode"], [state.sensorsLost ? "Lost" : "OK", "Equipment data", state.sensorsLost]];
    $("#kpis").innerHTML = tiles.map(([v, l, alert]) => `<div class="kpi ${alert ? "alert" : ""}"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
  }

  function supervisorPanel() {
    const list = D.work_orders.map((w) => {
      const a = ASSETS[w.asset_id];
      const waiting = w.approvals.filter((x) => x.outcome === "human").length;
      return `<div class="card click ${w.work_order_id === state.selectedWO ? "selected" : ""}" data-wo="${w.work_order_id}">
        <div class="row"><b>${esc(w.work_order_id)}</b><span><span class="pill pri-${w.priority}">${esc(w.priority)}</span>
          <span class="pill st st-${w.status}">${esc(w.status.replace("_", " "))}</span></span></div>
        <div>${esc(w.title)}</div>
        <div class="sub">${esc(a.asset_id)} · ${esc(a.region)} · ${w.source === "telemetry" ? "detected from telemetry" : "reported"}${waiting ? ` · <b>${waiting} approval${waiting > 1 ? "s" : ""} waiting</b>` : ""}</div></div>`;
    }).join("");
    const w = WOS[state.selectedWO];
    return `<h2>Dispatch board</h2><div class="sub">Agents propose; rules or a person approve. Labels show which tier answered and how fresh it is.</div>
      <h3>Work orders</h3>${list}${w ? woDetail(w) : ""}`;
  }

  function woDetail(w) {
    const a = ASSETS[w.asset_id];
    const d = w.diagnosis;
    const p1 = prov("W1"), p2 = prov("W2"), p3 = prov("W3"), p4 = prov("W4");
    const techRows = p2.tier === "none"
      ? `<div class="note">${esc(p2.how)}. The last ranking is shown below as a reference.</div>` : "";
    const techs = w.technicians.slice(0, 3).map((c) => `<tr><td><b>${esc(c.name)}</b><div class="muted">${esc(c.technician_id)}</div></td>
      <td>${Math.round(c.score * 100)}</td><td>${c.distance_km} km<div class="muted">${c.eta_min} min</div></td>
      <td>${c.available ? '<span class="ok">on shift</span>' : '<span class="muted">off</span>'}${c.missing_skills.length ? `<div class="bad">missing ${esc(c.missing_skills.join(", "))}</div>` : ""}</td></tr>`).join("");
    const loc = w.location;
    const resv = { cloud: "hard reservation", hub: "soft reservation (depot)", field: "soft, truck only" }[p4.tier] || "";
    const parts = w.parts.lines.map((l) => `<tr><td><b>${esc(l.part_number)}</b><div class="muted">${esc(l.description)}</div></td><td>${l.qty}</td>
      <td>${esc(l.pick_type)}<div class="muted">${esc(l.pick)}</div></td><td>${usd(l.unit_price * l.qty)}</td></tr>`).join("");
    const appr = w.approvals.map((x, i) => `<div class="appr"><div><b>${esc(x.action)}</b> <span class="muted">${esc(x.rule)}</span></div>
      ${x.outcome === "human" ? `<button class="btn small amber" data-approve="${i}">Approve · ${esc(x.approver)}</button>`
        : `<span class="${x.outcome === "auto" ? "ok" : "ok"}">${esc(x.approver)}</span>`}</div>`).join("");
    const feed = (state.feed[w.work_order_id] || []).map((f) => `<div><span class="muted">+${(f.t / 3600).toFixed(1)}h</span> ${esc(f.text)}</div>`).join("");
    const inTransit = state.queue.filter((q) => q.wo === w.work_order_id && q.dir === "up" && q.status !== "synced").length;
    const telAge = telemetryAgeForSupervisor();
    return `<h3 style="margin-top:22px">${esc(w.work_order_id)} · ${esc(a.asset_id)}</h3>
      <div class="sub">${esc(a.model)} · ${esc(a.site_name)} · criticality ${esc(a.criticality)} · site coverage <b>${esc(a.coverage)}</b></div>
      ${!d.safe_to_run ? `<div class="safety">${d.safety_override ? "Unsafe to run: edge safety rule fired. Agents cannot override this." : "Unsafe to run: shutdown recommended."}</div>` : ""}
      <h3><span><span class="wf">W1</span> Diagnosis</span>${p1.html}</h3>${causesBlock(d)}
      ${w.ground_truth && w.ground_truth !== d.causes[0].cause_code ? `<div class="note">Demo note: the simulator's real cause is ${esc(w.ground_truth)}. The rule-based diagnosis needs a technician to confirm.</div>` : ""}
      <h3><span><span class="wf">W2</span> Technician</span>${p2.html}</h3>${techRows}
      <table class="mini"><tr><th>Technician</th><th>Score</th><th>Drive</th><th>Status</th></tr>${techs}</table>
      <div class="sub">Needs: ${esc(w.skills_required.join(", "))} · est. ${w.est_hours} h</div>
      <h3><span><span class="wf">W3</span> Repair location</span>${p3.html}</h3>
      <div class="card"><b>${loc.location === "workshop" ? `Workshop (${esc(DEPOTS[loc.workshop_id]?.city || loc.workshop_id)})` : "On site"}</b>
        <span class="muted">· on-site ${loc.score_on_site} vs workshop ${loc.score_workshop}</span>
        <div class="sub">${loc.factors.map((f) => `${esc(f.factor)} → ${esc(f.favors.replace("_", " "))}`).join(" · ")}</div>
        ${loc.note ? `<div class="note">${esc(loc.note)}</div>` : ""}</div>
      <h3><span><span class="wf">W4</span> Parts</span>${p4.html}</h3>
      <table class="mini"><tr><th>Part</th><th>Qty</th><th>Source</th><th>Cost</th></tr>${parts}</table>
      <div class="sub">Total ${usd(w.parts.total_usd)} · ${esc(resv)}</div>
      <h3>Approvals <span class="muted" style="font-weight:400;font-size:12px">rule-based</span></h3>${appr}
      <h3>Live telemetry ${telAge === null ? '<span class="prov none">no data</span>' : `<span class="prov edge">Edge <span class="conf">· ${fmtAge(telAge)}</span></span>`}</h3>
      ${telemetryBlock(w.asset_id, telAge, state.sensorsLost ? "The site gateway isn't reporting (M6). Diagnosis falls back to guided inspection by the technician." : "")}
      <h3>Activity (as seen by the cloud)</h3><div class="feed">${feed}</div>
      ${inTransit ? `<div class="note">${inTransit} update${inTransit > 1 ? "s" : ""} from the field ${inTransit > 1 ? "are" : "is"} still in the technician's outbox or at the hub.</div>` : ""}`;
  }

  function approve(w, i) {
    const x = w.approvals[i];
    x.outcome = "approved"; x.approver = `${x.approver} (approved)`;
    if (!w.approvals.some((y) => y.outcome === "human")) {
      w.status = "assigned"; w.assigned_technician_id = w.technicians[0].technician_id;
      ASSETS[w.asset_id].work_order_id = w.work_order_id;
      state.feed[w.work_order_id].push({ t: state.simOffset, text: `Approved; assigned to ${TECHS[w.assigned_technician_id].name}` });
      enqueue("down", "P1", w.work_order_id, `Assignment ${w.work_order_id}`, "assign", { tech: w.assigned_technician_id });
      toast(`${w.work_order_id} assigned to ${TECHS[w.assigned_technician_id].name}`);
    }
    render();
  }

  // ------------------------------------------------------------------ technician
  function myJobs() {
    return D.work_orders.filter((w) => state.techView[w.work_order_id]?.assigned === state.techId && state.techView[w.work_order_id].status !== "completed");
  }

  function technicianPanel() {
    const t = TECHS[state.techId];
    const opts = D.technicians.map((x) => `<option value="${x.technician_id}" ${x.technician_id === state.techId ? "selected" : ""}>${esc(x.name)} · ${esc(DEPOTS[x.home_depot].city)}</option>`).join("");
    const jobs = myJobs();
    const pendingDown = state.queue.filter((q) => q.dir === "down" && q.status !== "synced" && q.payload.tech === state.techId).length;
    let body;
    if (!jobs.length) {
      body = `<div class="empty">No assigned jobs on this device.${pendingDown ? `<br>${pendingDown} new assignment waiting for a connection.` : ""}
        <br><span class="sub">Tip: approve a work order in the Supervisor view, or pick another technician.</span></div>`;
    } else {
      const w = jobs[0];
      const a = ASSETS[w.asset_id];
      const c = w.technicians.find((x) => x.technician_id === state.techId) || w.technicians[0];
      const tabs = [["diagnose", "Diagnose"], ["procedure", "Procedure + LOTO"], ["pack", "Mission pack"], ["parts", "Parts"], ["telemetry", "Live data"], ["closeout", "Close out"], ["outbox", `Outbox (${state.queue.filter((q) => q.dir === "up" && q.status !== "synced").length})`]];
      body = `<div class="card"><div class="row"><b>${esc(w.work_order_id)}</b><span class="pill pri-${w.priority}">${esc(w.priority)}</span></div>
          <div>${esc(w.title)}</div>
          <div class="sub">${esc(a.asset_id)} · ${esc(a.model)} · ${c.distance_km} km, about ${c.eta_min} min drive</div>
          <div class="sub">${esc(a.access_notes)}${a.hazards.length ? ` · <b>Hazards:</b> ${esc(a.hazards.join("; "))}` : ""}</div></div>
        ${!w.diagnosis.safe_to_run ? `<div class="safety">Do not run this unit. ${w.diagnosis.safety_override ? "The edge safety rule tripped." : "Shutdown recommended."}</div>` : ""}
        ${jobs.length > 1 ? `<div class="sub">+${jobs.length - 1} more job(s) after this one</div>` : ""}
        <div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button class="tab ${state.techTab === k ? "active" : ""}" data-tab="${k}">${esc(l)}</button>`).join("")}</div>
        ${techTab(w, a)}`;
    }
    return `<h2>My jobs</h2>
      <div class="row" style="margin:6px 0 4px"><select id="tech-select" aria-label="Technician" style="flex:1">${opts}</select></div>
      <div class="sub">Truck ${esc(t.truck_id)} · ${esc(t.skills.join(", "))}</div>${body}`;
  }

  function techTab(w, a) {
    const tab = state.techTab;
    if (tab === "diagnose") {
      const p = prov("W1");
      if (state.sensorsLost) {
        const model = a.model;
        const syms = [...new Set((D.manuals[model] || []).filter((m) => m.title.startsWith("Troubleshooting"))
          .flatMap((m) => (m.text.match(/Typical symptoms: ([^.]*)\./) || ["", ""])[1].split("; ")).filter(Boolean))];
        const sel = state.inspection[w.work_order_id] || new Set();
        const ranked = (D.manuals[model] || []).filter((m) => m.title.startsWith("Troubleshooting")).map((m) => {
          const s = (m.text.match(/Typical symptoms: ([^.]*)\./) || ["", ""])[1].split("; ");
          const hit = s.filter((x) => sel.has(x)).length;
          return { title: m.title.replace("Troubleshooting: ", ""), code: (m.text.match(/Fault code (\S+)\./) || ["", ""])[1], hit };
        }).sort((x, y) => y.hit - x.hit);
        return `<h3><span><span class="wf">W1</span> Guided inspection</span><span class="prov field">Device <span class="conf">· sensors lost</span></span></h3>
          <div class="note">No live data from the site gateway (M6). Tick what you observe; the device ranks causes from the mission pack.</div>
          ${syms.map((s) => `<label class="check"><input type="checkbox" data-sym="${esc(s)}" ${sel.has(s) ? "checked" : ""}><span>${esc(s)}</span></label>`).join("")}
          <h3>Likely causes</h3>${ranked.map((r) => `<div class="cause"><span>${esc(r.title)} <span class="muted">${esc(r.code)}</span></span><div class="bar"><span style="width:${Math.min(r.hit * 34, 100)}%"></span></div><b>${r.hit}</b></div>`).join("")}`;
      }
      return `<h3><span><span class="wf">W1</span> Diagnosis</span>${p.html}</h3><div class="sub">${esc(p.how)}</div>${causesBlock(w.diagnosis)}
        <h3>Evidence</h3>${w.diagnosis.evidence.map((e) => `<div class="sub">• ${esc(e)}</div>`).join("") || '<div class="sub">No alarms yet</div>'}`;
    }
    if (tab === "procedure") {
      const done = state.checklist[w.work_order_id] || new Set();
      return `<h3>Lockout / tagout <span class="muted" style="font-weight:400;font-size:12px">each step is logged as a P0 safety record</span></h3>
        ${D.loto.map((s, i) => `<label class="check"><input type="checkbox" data-loto="${i}" ${done.has(i) ? "checked disabled" : ""}><span>${i + 1}. ${esc(s)}</span></label>`).join("")}
        <h3>Procedure: ${esc(w.diagnosis.causes[0].description)}</h3>
        ${w.procedure.map((s, i) => `<div class="check"><b>${i + 1}.</b><span>${esc(s)}</span></div>`).join("")}`;
    }
    if (tab === "pack") {
      const hist = (D.history[a.asset_id] || []).slice(0, 5);
      return `<div class="note">Mission pack synced at the depot. Fully available offline.</div>
        <h3>Manual: ${esc(a.model)}</h3>${(D.manuals[a.model] || []).map((m) => `<details><summary>${esc(m.title)}</summary><pre>${esc(m.text)}</pre></details>`).join("")}
        <h3>Past repairs on ${esc(a.asset_id)}</h3>${hist.length ? hist.map((h) => `<div class="card"><div class="row"><b>${esc(h.cause_code)}</b><span class="muted">${esc(h.date)}</span></div>
          <div class="sub">${esc(h.notes)} · ${h.labor_hours} h · ${h.first_time_fix ? '<span class="ok">first-time fix</span>' : '<span class="bad">return visit</span>'}</div></div>`).join("") : '<div class="sub">No previous repairs</div>'}`;
    }
    if (tab === "parts") {
      const p = prov("W4");
      const truck = state.truck[state.techId];
      const rows = w.parts.lines.map((l) => {
        const have = truck[l.part_number] || 0;
        return `<tr><td><b>${esc(l.part_number)}</b><div class="muted">${esc(l.description)}</div></td><td>${l.qty}</td>
          <td class="${have >= l.qty ? "ok" : "bad"}">${have}</td>
          <td><button class="btn small ghost" data-use="${esc(l.part_number)}" ${have ? "" : "disabled"}>Use 1</button></td></tr>`;
      }).join("");
      const missing = w.parts.lines.filter((l) => (truck[l.part_number] || 0) < l.qty);
      return `<h3><span><span class="wf">W4</span> Parts for this job</span>${p.html}</h3><div class="sub">${esc(p.how)}</div>
        <table class="mini"><tr><th>Part</th><th>Need</th><th>On truck</th><th></th></tr>${rows}</table>
        ${missing.length ? `<div class="note">Not on the truck: ${missing.map((l) => `${esc(l.part_number)} from ${esc(l.pick_type)} ${esc(l.pick)}`).join(", ")}.${state.mode === "M5" ? " Offline: the request waits in the outbox." : ""}</div>` : ""}
        <h3>Truck stock</h3><table class="mini">${Object.entries(truck).map(([pn, q]) => `<tr><td>${esc(pn)}</td><td>${q}</td></tr>`).join("")}</table>`;
    }
    if (tab === "telemetry") {
      return `<h3>Live data <span class="prov edge">Edge <span class="conf">· local link</span></span></h3>
        <div class="sub">Read straight from the site gateway over Wi-Fi/BLE, so it works with no WAN.</div>
        ${telemetryBlock(a.asset_id, state.sensorsLost ? null : 5, "The site gateway isn't reporting (M6). Use the guided inspection on the Diagnose tab and record readings by hand.")}`;
    }
    if (tab === "closeout") {
      return `<h3><span><span class="wf">W6</span> Close out</span></h3>
        <label class="sub" for="co-cause">Confirmed cause</label>
        <select id="co-cause" style="width:100%;margin:4px 0 8px">${w.diagnosis.causes.map((c) => `<option value="${esc(c.cause_code)}">${esc(c.description)} (${esc(c.cause_code)})</option>`).join("")}</select>
        <label class="sub" for="co-notes">Findings</label>
        <textarea id="co-notes" rows="3" style="width:100%;margin:4px 0 8px" placeholder="What you found and did"></textarea>
        <div class="row" style="justify-content:flex-start;gap:8px;flex-wrap:wrap">
          <button class="btn ghost" id="co-photo">Attach photo (3.2 MB)</button>
          <button class="btn ghost" id="co-findings">Save findings</button>
          <button class="btn amber" id="co-complete">Complete job</button></div>
        <div class="sub" style="margin-top:8px">Findings and status are P1 and go out first. Photos are P4 and wait for a good link (M0).</div>`;
    }
    // outbox
    const items = state.queue.filter((q) => q.dir === "up").slice().reverse();
    return `<h3>Outbox <span class="muted" style="font-weight:400;font-size:12px">sent in priority order when the link allows</span></h3>
      ${items.length ? items.map((q) => `<div class="outbox-item"><span class="prio ${q.prio}" title="${PRIO_LABEL[q.prio]}">${q.prio}</span>
        <span>${esc(q.text)}<div class="muted">${esc(q.wo)}</div></span>
        <span class="${q.status === "synced" ? "q-synced" : q.status === "hub" ? "q-hub" : "q-queued"}">${q.status === "synced" ? "synced" : q.status === "hub" ? "at hub" : "queued"}</span></div>`).join("")
        : '<div class="empty">Nothing recorded yet</div>'}`;
  }

  function techRecord(prio, text, kind, payload) {
    const w = myJobs()[0];
    if (!w) return;
    enqueue("up", prio, w.work_order_id, text, kind, payload);
    const st = state.queue[state.queue.length - 1].status;
    toast(st === "synced" ? `Synced: ${text}` : st === "hub" ? `Delivered to depot hub: ${text}` : `Queued offline: ${text}`);
  }

  // ------------------------------------------------------------------ banner + controls
  function banner() {
    const m = mode();
    const ln = (label, st) => `<span>${label}: <span class="${st === "down" ? "link-down" : st === "flaky" ? "link-flaky" : "link-up"}">${st === "up" ? "up" : st}</span></span>`;
    const queued = state.queue.filter((q) => q.status !== "synced").length;
    $("#mode-banner").style.background = `color-mix(in srgb, ${m.color} 14%, white)`;
    $("#mode-banner").innerHTML = `<span class="badge" style="background:${m.color};${m.dark ? "color:var(--text)" : ""}">${state.mode} ${esc(m.name)}</span>
      ${state.sensorsLost ? '<span class="badge" style="background:var(--m6)">M6 Sensors lost</span>' : ""}
      <span>${esc(m.desc)}${state.sensorsLost ? "; site gateway not reporting" : ""}.</span>
      <span class="links">${ln("Device→cloud", m.links.cloud)}${ln("Device→hub", m.links.hub)}${ln("Edge→cloud", m.links.edgeCloud)}${ln("Cloud AI", m.links.llm)}</span>
      ${queued ? `<span><b>${queued}</b> message${queued > 1 ? "s" : ""} waiting to sync</span>` : ""}`;
    $("#mode-chips").innerHTML = Object.entries(MODES).map(([k, v]) => `<button class="mode-chip ${k === state.mode ? "active" : ""} ${v.dark ? "dark-text" : ""}" style="background:${v.color}" data-mode="${k}" title="${esc(v.desc)}">${k}</button>`).join("");
    $("#m6").checked = state.sensorsLost;
    $("#sim-clock").textContent = fmtTime(simNow());
  }

  function setMode(m, fromScenario = false) {
    const wasOnline = ["up", "slow", "flaky"].includes(mode().links.cloud);
    state.mode = m;
    const nowOnline = ["up", "slow", "flaky"].includes(mode().links.cloud);
    if (wasOnline && !nowOnline) state.offlineSince = state.simOffset;
    if (nowOnline && state.mode !== "M2") state.offlineSince = null;
    if (!fromScenario) stopScenario();
    syncTick();
    render();
  }

  function setPersona(p) {
    state.persona = p;
    for (const b of document.querySelectorAll(".persona-btn")) b.classList.toggle("active", b.dataset.persona === p);
    render(); focusMap();
  }

  // scenarios
  function scenarioUI() {
    $("#scenario-select").innerHTML = `<option value="">Manual (no scenario)</option>` + D.scenarios.map((s) => `<option value="${s.name}">${esc(s.name.replaceAll("_", " "))}</option>`).join("");
  }
  function drawScenarioBar() {
    const s = D.scenarios.find((x) => x.name === state.scenario);
    const bar = $("#scenario-bar");
    if (!s) { bar.innerHTML = ""; $("#scenario-note").textContent = ""; return; }
    bar.innerHTML = s.segments.map((g, i) => {
      const end = s.segments[i + 1]?.start_s ?? s.duration_s;
      return `<div class="seg" title="${g.mode}${g.telemetry_lost ? " + M6" : ""} ${esc(g.note)}" style="width:${((end - g.start_s) / s.duration_s) * 100}%;background:var(--${g.mode.toLowerCase()})${g.telemetry_lost ? ";background-image:repeating-linear-gradient(45deg,transparent 0 4px,rgba(255,255,255,.45) 4px 7px)" : ""}"></div>`;
    }).join("") + `<div class="cursor" style="left:${(state.scenarioT / s.duration_s) * 100}%"></div>`;
  }
  function stopScenario() {
    state.playing = false; clearInterval(state.timer); $("#scenario-play").textContent = "Play";
  }
  function playScenario() {
    const s = D.scenarios.find((x) => x.name === state.scenario);
    if (!s) return toast("Pick a scenario first");
    if (state.playing) return stopScenario();
    if (state.scenarioT >= s.duration_s) state.scenarioT = 0;
    state.playing = true; $("#scenario-play").textContent = "Pause";
    const stepS = Math.max(300, s.duration_s / 120); // ~120 ticks per scenario
    state.timer = setInterval(() => {
      state.scenarioT += stepS; state.simOffset += stepS;
      if (state.scenarioT >= s.duration_s) { state.scenarioT = s.duration_s - 1; stopScenario(); toast("Scenario finished"); }
      const seg = [...s.segments].reverse().find((g) => g.start_s <= state.scenarioT);
      $("#scenario-note").textContent = `${(state.scenarioT / 3600).toFixed(1)} h · ${seg.note || MODES[seg.mode].name}`;
      if (seg.mode !== state.mode || seg.telemetry_lost !== state.sensorsLost) {
        state.sensorsLost = seg.telemetry_lost;
        setMode(seg.mode, true);
      } else {
        syncTick(); banner(); drawScenarioBar();
      }
    }, 250);
  }

  // ------------------------------------------------------------------ render + events
  function render() {
    banner(); kpis(); drawScenarioBar();
    $("#panel").innerHTML = state.persona === "supervisor" ? supervisorPanel() : technicianPanel();
    drawMap();
  }

  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-persona],[data-mode],[data-wo],[data-approve],[data-tab],[data-use],#co-photo,#co-findings,#co-complete,#scenario-play");
    if (!t) return;
    if (t.dataset.persona) return setPersona(t.dataset.persona);
    if (t.dataset.mode) return setMode(t.dataset.mode);
    if (t.dataset.wo) { state.selectedWO = t.dataset.wo; render(); focusMap(); return; }
    if (t.dataset.approve) return approve(WOS[state.selectedWO], Number(t.dataset.approve));
    if (t.dataset.tab) { state.techTab = t.dataset.tab; return render(); }
    if (t.dataset.use) {
      const pn = t.dataset.use; state.truck[state.techId][pn] -= 1;
      techRecord("P1", `Used 1 × ${pn} from truck`, "parts", { pn });
      return render();
    }
    if (t.id === "co-photo") { techRecord("P4", "Photo of failed component (3.2 MB)", "photo"); return render(); }
    if (t.id === "co-findings") {
      const cause = $("#co-cause").value, notes = $("#co-notes").value.trim();
      techRecord("P1", `Findings: ${cause}${notes ? ` · ${notes}` : ""}`, "findings"); return render();
    }
    if (t.id === "co-complete") {
      const w = myJobs()[0];
      techRecord("P1", `Job complete, cause ${$("#co-cause").value}`, "complete");
      state.techView[w.work_order_id].status = "completed"; state.techTab = "diagnose";
      return render();
    }
    if (t.id === "scenario-play") return playScenario();
  });
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t.id === "tech-select") { state.techId = t.value; state.techTab = "diagnose"; render(); focusMap(); }
    else if (t.id === "m6") { state.sensorsLost = t.checked; stopScenario(); render(); }
    else if (t.id === "scenario-select") { stopScenario(); state.scenario = t.value || null; state.scenarioT = 0; drawScenarioBar(); }
    else if (t.dataset.loto) {
      const w = myJobs()[0]; const set = state.checklist[w.work_order_id] ||= new Set();
      set.add(Number(t.dataset.loto));
      techRecord("P0", `LOTO step ${Number(t.dataset.loto) + 1} confirmed`, "loto"); render();
    } else if (t.dataset.sym !== undefined) {
      const w = myJobs()[0]; const set = state.inspection[w.work_order_id] ||= new Set();
      t.checked ? set.add(t.dataset.sym) : set.delete(t.dataset.sym); render();
    }
  });

  // background sync attempts (drives intermittent mode)
  setInterval(() => syncTick(), 1500);

  scenarioUI();
  state.scenarioT = 0;
  render();
  focusMap();
})();
