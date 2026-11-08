/* hybrid-ai Field Ops demo dashboard.
 * Data: data.js (window.HYBRID_DATA) from `python -m hybrid_ai.demo.build_data`.
 * Repair plans: /api/recommendations (SQLite) when served by `python -m hybrid_ai.demo.server`;
 * falls back to the embedded data when the API isn't there.
 * Network behavior, routing and costs are simulated in the page, following docs/DESIGN.md §5.
 */
(() => {
  "use strict";
  const D = window.HYBRID_DATA;
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ------------------------------------------------------------------ mode model (DESIGN.md §5)
  const MODES = {
    M0: { name: "Connected", color: "var(--m0)", dark: false, desc: "Full cloud reasoning, live data", links: { cloud: "up", hub: "up", edgeCloud: "up", llm: "up" }, tel: 30 },
    M1: { name: "Constrained", color: "var(--m1)", dark: true, desc: "Slow link: compact context, media deferred", links: { cloud: "slow", hub: "slow", edgeCloud: "slow", llm: "up" }, tel: 240 },
    M2: { name: "Intermittent", color: "var(--m2)", dark: true, desc: "Link drops: local first, writes provisional", links: { cloud: "flaky", hub: "flaky", edgeCloud: "flaky", llm: "up" }, tel: 900 },
    M3: { name: "Cloud AI down", color: "var(--m3)", dark: false, desc: "Network fine, model API failing", links: { cloud: "up", hub: "up", edgeCloud: "up", llm: "down" }, tel: 30 },
    M4: { name: "Hub island", color: "var(--m4)", dark: false, desc: "WAN down, depot hub reachable", links: { cloud: "down", hub: "up", edgeCloud: "down", llm: "down" }, tel: null },
    M5: { name: "Fully offline", color: "var(--m5)", dark: false, desc: "Only the device and the site gateway", links: { cloud: "down", hub: "down", edgeCloud: "down", llm: "down" }, tel: null },
  };
  const TIER_NAME = { cloud: "Cloud", hub: "Hub", field: "Device", edge: "Edge", none: "Unavailable" };
  const PRIO_LABEL = { P0: "Safety", P1: "Control", P2: "Context", P3: "Knowledge", P4: "Bulk" };
  const PERSONA_NAME = { supervisor: "Supervisor", technician: "Technician", walkthrough: "Assigned tech" };

  // Model cost profiles: prefill and decode speed in tokens per second.
  const MODELS = {
    "claude-opus-5-5": { tier: "cloud", prefill: 4000, decode: 70 },
    "claude-haiku-5-5": { tier: "cloud", prefill: 9000, decode: 170 },
    "hub-local-14b": { tier: "hub", prefill: 1500, decode: 40 },
    "device-local-3b": { tier: "field", prefill: 600, decode: 25 },
  };
  const NET_MS = { cloud: { M0: 90, M1: 950, M2: 450, M3: 90, M4: 0, M5: 0 }, hub: { M0: 60, M1: 700, M2: 320, M3: 60, M4: 140, M5: 0 } };
  const BW_KBPS = { M0: 10000, M1: 128, M2: 512, M3: 10000, M4: 2000, M5: 1 };

  // ------------------------------------------------------------------ state
  const byId = (arr, key) => Object.fromEntries(arr.map((x) => [x[key], x]));
  const ASSETS = byId(D.assets, "asset_id");
  const TECHS = byId(D.technicians, "technician_id");
  const DEPOTS = byId(D.depots, "depot_id");
  const WOS = byId(D.work_orders, "work_order_id");
  const NOW0 = new Date(D.generated.now).getTime();
  const WT_WO = D.work_orders.find((w) => w.assigned_technician_id);

  const state = {
    persona: "supervisor", mode: "M0", sensorsLost: false, simOffset: 0, offlineSince: null,
    selectedWO: D.work_orders[0]?.work_order_id,
    techId: WT_WO?.assigned_technician_id || D.technicians[0].technician_id,
    techTab: "plan", techPos: null,
    queue: [], feed: {}, techView: {}, van: Object.fromEntries(D.technicians.map((t) => [t.technician_id, Object.fromEntries(t.van_stock.map((p) => [p.part_number, p.qty]))])),
    inspection: {}, plans: {}, stepLocal: {},
    scenario: null, scenarioT: 0, playing: false, timer: null,
    log: [], chat: [], liveOpen: true, assistantOpen: false,
    api: false,
  };
  for (const w of D.work_orders) {
    state.feed[w.work_order_id] = [{ t: 0, text: w.source === "telemetry" ? "Created from telemetry alarm" : "Reported by site operator" }];
    if (w.assigned_technician_id) state.techView[w.work_order_id] = { status: w.status, assigned: w.assigned_technician_id };
  }
  let seq = 0, logSeq = 0;

  // ------------------------------------------------------------------ helpers
  const simNow = () => NOW0 + state.simOffset * 1000;
  const fmtTime = (ms) => new Date(ms).toISOString().replace("T", " ").slice(0, 16) + " UTC";
  const fmtAge = (s) => (s == null ? "no data" : s < 60 ? `${Math.round(s)} s old` : s < 3600 ? `${Math.round(s / 60)} min old` : `${(s / 3600).toFixed(1)} h old`);
  const fmtMs = (ms) => (ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);
  const fmtTok = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
  const usd = (n) => "$" + n.toLocaleString("en-US");
  const mode = () => MODES[state.mode];
  const offlineAge = () => (state.offlineSince == null ? null : Math.max(0, state.simOffset - state.offlineSince) + 1800);
  const isField = (who) => who !== "supervisor";
  const firstName = (id) => TECHS[id].name.split(" ")[0];

  // What can this persona reach right now? The supervisor sits in the office (always online);
  // the mode describes the technician's / site's link.
  function reach(who) {
    const L = mode().links;
    const up = (s, p) => s === "up" || s === "slow" || (s === "flaky" && Math.random() < p);
    if (!isField(who)) return { cloud: true, hub: true, llm: L.llm === "up", edgeCloud: !state.sensorsLost && up(L.edgeCloud, 0.5) };
    return { cloud: up(L.cloud, 0.45), hub: up(L.hub, 0.5), llm: L.llm === "up", edgeCloud: !state.sensorsLost && up(L.edgeCloud, 0.5) };
  }

  function costMs(p) {
    let ms = 0;
    if (p.tier === "cloud" || p.tier === "hub") {
      const m = isField(p.who) ? state.mode : "M0";
      ms += (NET_MS[p.tier][m] || 60) + ((p.kb || 2) * 8 / (BW_KBPS[m] || 10000)) * 1000;
    } else if (p.tier === "edge") ms += 15;
    else ms += 5;
    if (p.model) ms += (p.tin / MODELS[p.model].prefill + p.tout / MODELS[p.model].decode) * 1000;
    else ms += 20 + Math.random() * 40;
    return Math.round(ms * (0.85 + Math.random() * 0.3));
  }

  // ------------------------------------------------------------------ router: where each request runs, and why
  function route(tool, who) {
    const m = state.mode, r = reach(who), M = isField(who) ? `${m} ${MODES[m].name}` : "Office (online)";
    const P = (tier, why, extra = {}) => ({ tier, why, model: null, tin: 0, tout: 0, kb: 2, status: "ok", ...extra });
    switch (tool) {
      case "diagnose_issue":
        if (state.sensorsLost && isField(who)) return P("field", `${M} + M6: no telemetry, so the device ranks causes from what the technician observes`, { model: "device-local-3b", tin: 500, tout: 120 });
        if (isField(who) && m === "M2") return P("field", `${M}: local first on a flaky link; cloud gives a second opinion later`, { model: "device-local-3b", tin: 1400, tout: 180 });
        if (r.cloud && r.llm) return P("cloud", m === "M1" && isField(who) ? `${M}: slow link, so only edge features are sent (no raw waveforms)` : `${M}: cloud reachable, so the large model with full fleet history`, { model: "claude-opus-5-5", tin: m === "M1" && isField(who) ? 700 : 2600, tout: 260, kb: m === "M1" && isField(who) ? 3 : 40 });
        if (r.hub) return P("hub", m === "M3" ? `${M}: cloud model API failing, so the hub model reasons over live cloud data` : `${M}: no WAN, so the depot hub model with regional history`, { model: "hub-local-14b", tin: 1800, tout: 220, kb: 6 });
        return P("field", `${M}: no uplink, so the device model over edge rules and the mission pack`, { model: "device-local-3b", tin: 1400, tout: 180 });
      case "find_technicians":
        if (r.cloud) return P("cloud", m === "M3" ? `${M}: dispatch optimizer is deterministic, so it doesn't need the cloud AI` : m === "M2" && isField(who) ? `${M}: cloud answered within the 3 s deadline` : `${M}: live roster, GPS and SLA in the cloud`, { kb: 6 });
        if (r.hub) return P("hub", m === "M2" ? `${M}: cloud missed the 3 s deadline, so the hub roster snapshot (provisional)` : `${M}: hub roster snapshot, 3 h old (provisional)`);
        return P("none", `${M}: dispatch isn't available offline; call the dispatcher`, { status: "failed" });
      case "recommend_repair_location":
        if (isField(who) && (m === "M2" || m === "M5")) return P("field", `${M}: rule score computed on the device`);
        if (r.cloud) return P("cloud", `${M}: learned + rule score in the cloud`);
        if (r.hub) return P("hub", `${M}: rule score at the hub`);
        return P("field", `${M}: rule score computed on the device`);
      case "check_parts":
        if (r.cloud) return P("cloud", `${M}: live ERP stock (van, depot, warehouse, vendor)`);
        if (r.hub) return P("hub", `${M}: depot stock live, other stock from snapshot`);
        return P("field", `${M}: no uplink, so van stock only`);
      case "reserve_parts":
        if (r.cloud) return P("cloud", `${M}: hard reservation in the ERP`);
        if (r.hub) return P("hub", `${M}: soft reservation at the depot hub`);
        return P("field", `${M}: soft reservation queued in the outbox`, { status: "queued" });
      case "search_knowledge":
        if (isField(who)) return P("field", "Mission pack already has this asset's manuals and history, so no network needed");
        return P("cloud", "Full knowledge base in the cloud");
      case "get_live_telemetry":
        if (isField(who)) return state.sensorsLost ? P("none", `${M} + M6: site gateway not reporting`, { status: "failed" }) : P("edge", "Local Wi-Fi/BLE link to the site gateway, no WAN needed");
        if (state.sensorsLost) return P("none", "M6: site gateway not reporting", { status: "failed" });
        return r.edgeCloud ? P("cloud", `${m}: edge streams features to the cloud`) : P("cloud", `${m}: edge-to-cloud link down, so the last known copy`, { status: "stale" });
      case "repair_db.get_plan":
        if (r.cloud) return P("cloud", `${M}: live plan from the repair recommendations DB`, { kb: 12 });
        return P("field", `${M}: copy of the plan from the mission pack`);
      case "repair_db.update_step": case "repair_db.outcome": case "update_work_order":
        if (r.cloud) return P("cloud", `${M}: written to the repair recommendations DB`);
        if (r.hub && m === "M4") return P("hub", `${M}: delivered to the depot hub; forwarded when the WAN returns`, { status: "queued" });
        return P("field", `${M}: queued in the device outbox`, { status: "queued" });
      case "sync_mission_pack":
        if (r.cloud && (m === "M0" || !isField(who))) return P("cloud", "At the depot on good Wi-Fi: P3 knowledge download", { kb: 4200 });
        return P("none", `${M}: pack downloads wait for a good link (P3)`, { status: "failed" });
      case "compose_answer":
        if (r.cloud && r.llm) return P("cloud", `${M}: small fast cloud model writes the answer`, { model: "claude-haiku-5-5", tin: 900, tout: 140, kb: 4 });
        if (r.hub) return P("hub", m === "M3" ? `${M}: cloud AI down, so the hub model writes the answer` : `${M}: hub model writes the answer`, { model: "hub-local-14b", tin: 900, tout: 120, kb: 4 });
        return P("field", `${M}: device model writes the answer`, { model: "device-local-3b", tin: 700, tout: 100 });
      case "local_status":
        return P("field", "Answered from the device's own state, no model needed");
      default:
        return P("field", "local");
    }
  }

  function callTool(tool, who, request, extra = {}) {
    const p = { ...route(tool, who), who, ...extra };
    p.ms = p.status === "failed" ? Math.round((isField(who) ? 3000 : 400) * (p.tier === "none" ? 1 : 0.2)) : costMs(p);
    const entry = { id: ++logSeq, t: state.simOffset, who, via: extra.via, request, tool, tier: p.tier, model: p.model, why: p.why, ms: p.ms, tin: p.tin, tout: p.tout, status: p.status };
    state.log.push(entry);
    if (state.log.length > 400) state.log.shift();
    renderLive(entry.id);
    return p;
  }

  // ------------------------------------------------------------------ provenance chips for workflow panels
  function provFor(tool, who) {
    const p = route(tool, who);
    const conf = p.status === "failed" ? "unavailable" : p.tier === "cloud" ? (p.status === "stale" ? "stale" : "confirmed") : "provisional";
    let age = 0;
    if (p.tier === "hub") age = state.mode === "M3" ? 5 : 3 * 3600;
    if (p.tier === "field") age = offlineAge() ?? 600;
    const ageTxt = p.tier === "none" ? "" : ` · ${fmtAge(age)}`;
    return { ...p, conf, html: `<span class="prov ${p.tier}" title="${esc(p.why)}">${TIER_NAME[p.tier]} <span class="conf">· ${conf}${ageTxt}</span></span>` };
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

  // ------------------------------------------------------------------ API (repair recommendations DB)
  async function api(path, body) {
    if (!state.api) return null;
    try {
      const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
      return r.ok ? r.json() : null;
    } catch { return null; }
  }

  // Fallback plan built from embedded data (same structure as repair_db.get_plan).
  function planFromData(w) {
    const a = ASSETS[w.asset_id], top = w.diagnosis.causes[0];
    const steps = D.loto.map((s) => ["safety", s]);
    steps.push(["verify", `Confirm the diagnosis (${top.description}): check ${w.diagnosis.evidence.slice(0, 2).join("; ") || "the reported symptoms"}.`]);
    w.procedure.forEach((s) => steps.push(["repair", s]));
    if (w.parts.lines.length) steps.push(["repair", "Fit parts: " + w.parts.lines.map((p) => `${p.qty} x ${p.part_number} (${p.description})`).join(", ") + "."]);
    steps.push(["test", `Remove locks, restart and run loaded for 15 minutes; confirm ${Object.keys(D.telemetry[a.asset_id].thresholds).slice(0, 3).join(", ")} are back within limits.`]);
    steps.push(["closeout", "Record the confirmed cause, parts used and photos, then complete the work order."]);
    const refs = (D.manuals[a.model] || []).filter((m) => m.text.includes(top.cause_code) || m.title.toLowerCase().includes("lockout"))
      .map((m) => ({ kind: "manual", ref_id: m.doc_id, title: m.title, detail: m.text }))
      .concat((D.history[a.asset_id] || []).slice(0, 3).map((r) => ({ kind: "asset_repair", ref_id: r.date, title: `${r.date} · ${r.cause_code} on this asset`, detail: r.notes })));
    return {
      work_order_id: w.work_order_id, asset_id: a.asset_id, model: a.model, category: a.category, site_name: a.site_name,
      priority: w.priority, status: w.status, cause_code: top.cause_code, cause_description: top.description,
      severity: w.diagnosis.severity, safe_to_run: w.diagnosis.safe_to_run, safety_override: w.diagnosis.safety_override,
      repair_location: w.location.location, est_hours: w.est_hours, version: 1, generated_by: "diagnosis+logistics agents (rule fallback)",
      causes: w.diagnosis.causes.map((c, i) => ({ rank: i + 1, ...c })),
      steps: steps.map(([phase, instruction], i) => ({ seq: i + 1, phase, instruction, status: "todo" })),
      parts: w.parts.lines.map((p) => ({ part_number: p.part_number, description: p.description, qty: p.qty, source_type: p.pick_type, source_id: p.pick, unit_price: p.unit_price })),
      references: refs, outcome: null,
    };
  }

  async function loadPlan(woId, who, reason = "Open repair plan") {
    const p = callTool("repair_db.get_plan", who, reason);
    let plan = null, source = "pack";
    if (p.tier === "cloud") { plan = await api(`/api/recommendations/${woId}`); if (plan) source = "db"; }
    if (!plan) plan = state.plans[woId]?.plan || planFromData(WOS[woId]);
    state.plans[woId] = { plan, source, at: state.simOffset };
    return plan;
  }

  // ------------------------------------------------------------------ outbox / sync
  function enqueue(dir, prio, wo, text, kind, payload = {}) {
    const q = { id: ++seq, dir, prio, wo, text, kind, payload, status: "queued", created: state.simOffset, key: `dev-${state.techId}-${Date.now().toString(36)}-${seq}` };
    state.queue.push(q);
    syncTick(true);
    return q;
  }
  function allowed(prio) {
    switch (state.mode) {
      case "M0": case "M3": return true;
      case "M1": return prio !== "P4";
      case "M2": case "M4": return ["P0", "P1", "P2"].includes(prio);
      default: return false;
    }
  }
  function syncTick(immediate = false, forceWindow = false) {
    let changed = false;
    const order = { P0: 0, P1: 1, P2: 2, P3: 3, P4: 4 };
    const pending = state.queue.filter((q) => q.status !== "synced").sort((a, b) => order[a.prio] - order[b.prio] || a.id - b.id);
    for (const q of pending) {
      if (!allowed(q.prio)) continue;
      if (state.mode === "M4") { if (q.dir === "up" && q.status === "queued") { q.status = "hub"; changed = true; } continue; }
      const up = forceWindow || ["up", "slow"].includes(mode().links.cloud) || (mode().links.cloud === "flaky" && Math.random() < 0.45);
      if (!up || (immediate && state.mode === "M2" && !forceWindow)) continue;
      q.status = "synced"; changed = true;
      apply(q);
    }
    if (changed) render();
  }
  function apply(q) {
    const age = ((state.simOffset - q.created) / 3600).toFixed(1);
    if (q.dir === "up") {
      state.feed[q.wo] = state.feed[q.wo] || [];
      state.feed[q.wo].push({ t: state.simOffset, text: q.text });
      const tool = q.kind === "step" ? "repair_db.update_step" : q.kind === "complete" ? "repair_db.outcome" : q.kind === "photo" ? "upload_media" : "update_work_order";
      const entry = { id: ++logSeq, t: state.simOffset, who: "outbox", request: `Replay: ${q.text}`, tool, tier: "cloud", model: null,
        why: q.created === state.simOffset ? `${q.prio} sent immediately` : `Link back: ${q.prio} replayed after ${age} h (idempotency key keeps it single)`,
        ms: Math.round((q.kind === "photo" ? 3200 * 8 / (BW_KBPS[state.mode] || 10000) * 1000 : 120) * (0.85 + Math.random() * 0.3)), tin: 0, tout: 0, status: "ok" };
      if (q.created !== state.simOffset || q.status === "synced") { state.log.push(entry); renderLive(entry.id); }
      if (q.kind === "step") api(`/api/recommendations/${q.wo}/steps/${q.payload.seq}`, { status: "done", by: q.payload.by, idempotency_key: q.key, origin_tier: q.created === state.simOffset ? "cloud" : "field", note: q.payload.note });
      if (q.kind === "step" && state.stepLocal[q.wo]) state.stepLocal[q.wo][q.payload.seq] = "synced";
      if (q.kind === "complete") {
        WOS[q.wo].status = "completed"; ASSETS[WOS[q.wo].asset_id].status = "healthy";
        api(`/api/recommendations/${q.wo}/outcome`, { confirmed_cause: q.payload.cause, by: q.payload.by, notes: q.payload.notes || "" });
      }
    } else if (q.kind === "assign") {
      state.techView[q.wo] = { status: "assigned", assigned: q.payload.tech };
    }
  }

  // ------------------------------------------------------------------ map
  const map = L.map("map", { zoomControl: true }).setView([36.8, -119.4], 6);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
  const STATUS_COLOR = { healthy: "#2e8b57", warning: "#e0a100", fault: "#b83227" };
  const layers = { asset: L.layerGroup().addTo(map), depot: L.layerGroup().addTo(map), tech: L.layerGroup().addTo(map), route: L.layerGroup().addTo(map) };

  function assetPopup(a) {
    const wo = a.work_order_id ? `<br><a href="#" data-open-wo="${a.work_order_id}">${a.work_order_id}</a>` : "";
    return `<b>${esc(a.asset_id)}</b> · ${esc(a.model)}<br>${esc(a.category)}<br>${esc(a.site_name)} (${esc(a.region)})<br>
      Coverage: <b>${esc(a.coverage)}</b> · Status: <b style="color:${STATUS_COLOR[a.status]}">${a.status}</b>${wo}`;
  }
  function techLatLon() {
    const t = TECHS[state.techId];
    return state.techPos && state.persona === "walkthrough" ? state.techPos : [t.lat, t.lon];
  }
  function drawMap() {
    Object.values(layers).forEach((l) => l.clearLayers());
    const field = isField(state.persona);
    const job = field ? currentJob() : null;
    for (const d of D.depots) {
      L.marker([d.lat, d.lon], { icon: L.divIcon({ className: "", html: `<div class="depot-icon" style="width:26px;height:20px">${d.has_workshop ? "WS" : "HUB"}</div>`, iconSize: [26, 20] }), title: `${d.city} depot` })
        .bindPopup(`<b>${esc(d.city)} depot</b> (${esc(d.depot_id)})<br>Regional hub${d.has_workshop ? " + workshop" : ""}`).addTo(layers.depot);
    }
    for (const a of D.assets) {
      const hl = (!field && a.work_order_id === state.selectedWO) || (job && job.asset_id === a.asset_id);
      L.circleMarker([a.lat, a.lon], { radius: hl ? 11 : a.status === "healthy" ? 6 : 8, color: hl ? "#14232b" : "#ffffff", weight: hl ? 3 : 2, fillColor: STATUS_COLOR[a.status], fillOpacity: 0.95 })
        .bindPopup(assetPopup(a)).addTo(layers.asset);
    }
    const techs = field ? [TECHS[state.techId]] : D.technicians.filter((t) => t.on_shift);
    for (const t of techs) {
      const ini = t.name.split(" ").map((p) => p[0]).join("");
      const pos = field ? techLatLon() : [t.lat, t.lon];
      L.marker(pos, { icon: L.divIcon({ className: "", html: `<div class="tech-icon ${field ? "me" : ""}" style="width:24px;height:24px">${esc(ini)}</div>`, iconSize: [24, 24] }), title: t.name, zIndexOffset: 500 })
        .bindPopup(`<b>${esc(t.name)}</b> (${esc(t.technician_id)})<br>Van ${esc(t.van_id)} · ${esc(t.skills.join(", "))}`).addTo(layers.tech);
    }
    if (job) {
      const a = ASSETS[job.asset_id], t = TECHS[state.techId];
      L.polyline([[t.lat, t.lon], [a.lat, a.lon]], { color: "#14232b", weight: 3, dashArray: "6 6", opacity: 0.6 }).addTo(layers.route);
    }
  }
  map.on("popupopen", (e) => {
    const link = e.popup.getElement().querySelector("[data-open-wo]");
    if (link) link.addEventListener("click", (ev) => { ev.preventDefault(); setPersona("supervisor"); selectWO(link.dataset.openWo); });
  });
  function focusMap() {
    if (isField(state.persona)) {
      const job = currentJob(); const t = TECHS[state.techId];
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
    const breach = th.warn != null && (th.low_is_bad ? last <= th.warn : last >= th.warn);
    return `<div class="sig"><div class="row"><b>${esc(sig)}</b><span class="${breach ? "bad" : "muted"}">${last} ${esc(series.unit)}${th.warn != null ? ` · warn ${th.low_is_bad ? "<" : ">"} ${th.warn}` : ""}</span></div>
      <svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(sig)} trend">${guide(th.warn, "#e0a100")}${guide(th.trip, "#b83227")}
      <path d="${path}" fill="none" stroke="${stale ? "#93a7b0" : "#1b8a8f"}" stroke-width="2"/></svg></div>`;
  }
  function telemetryBlock(assetId, ageS, lostMsg) {
    const T = D.telemetry[assetId];
    if (ageS === null) return `<div class="note">${lostMsg}</div>`;
    const stale = ageS > 600;
    const al = T.alarms.slice(-3).map((a) => `<div><span class="pill ${a.severity === "critical" ? "pri-urgent" : "pri-soon"}">${esc(a.code)}</span> <span class="muted">${esc(a.ts.slice(11, 16))}</span></div>`).join("");
    return `${stale ? `<div class="note">Last known values, ${fmtAge(ageS)}. The edge-to-cloud link is down.</div>` : ""}
      ${T.series.map((s) => spark(s.signal, s, T.thresholds[s.signal], stale)).join("")}${al ? `<div class="sub" style="margin-top:4px">Recent alarms</div>${al}` : ""}`;
  }
  const causesBlock = (causes) => causes.map((c) => `<div class="cause"><span>${esc(c.description)} <span class="muted">${esc(c.cause_code)}</span></span>
    <div class="bar"><span style="width:${Math.round(c.probability * 100)}%"></span></div><b>${Math.round(c.probability * 100)}%</b></div>`).join("");

  // ------------------------------------------------------------------ KPIs
  function kpis() {
    const open = D.work_orders.filter((w) => w.status !== "completed");
    const pending = D.work_orders.reduce((n, w) => n + w.approvals.filter((a) => a.outcome === "human").length, 0);
    const faults = D.assets.filter((a) => a.status !== "healthy").length;
    const queued = state.queue.filter((q) => q.dir === "up" && q.status !== "synced").length;
    const tiles = state.persona === "supervisor"
      ? [[D.assets.length, "Compressors"], [faults, "Need attention", faults > 0], [open.length, "Open work orders"], [pending, "Approvals waiting", pending > 0], [queued, "Field updates in transit", queued > 0]]
      : [[myJobs().length, "My jobs"], [Object.values(state.van[state.techId]).reduce((a, b) => a + b, 0), "Parts in van"], [queued, "Outbox (not synced)", queued > 0], [state.mode, "Network mode"], [state.sensorsLost ? "Lost" : "OK", "Equipment data", state.sensorsLost]];
    $("#kpis").innerHTML = tiles.map(([v, l, alert]) => `<div class="kpi ${alert ? "alert" : ""}"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
  }

  // ------------------------------------------------------------------ supervisor
  function selectWO(id) {
    state.selectedWO = id;
    const w = WOS[id];
    const req = `Review ${id}`;
    for (const tool of ["diagnose_issue", "find_technicians", "recommend_repair_location", "check_parts"]) callTool(tool, "supervisor", `${req}: ${tool.replaceAll("_", " ")}`);
    callTool("get_live_telemetry", "supervisor", `${req}: telemetry for ${w.asset_id}`);
    render(); focusMap();
  }
  function supervisorPanel() {
    const list = D.work_orders.map((w) => {
      const a = ASSETS[w.asset_id];
      const waiting = w.approvals.filter((x) => x.outcome === "human").length;
      return `<div class="card click ${w.work_order_id === state.selectedWO ? "selected" : ""}" data-wo="${w.work_order_id}">
        <div class="row"><b>${esc(w.work_order_id)}</b><span><span class="pill pri-${w.priority}">${esc(w.priority)}</span> <span class="pill st st-${w.status}">${esc(w.status.replace("_", " "))}</span></span></div>
        <div>${esc(w.title)}</div>
        <div class="sub">${esc(a.asset_id)} · ${esc(a.region)} · ${w.source === "telemetry" ? "detected from telemetry" : "reported"}${waiting ? ` · <b>${waiting} approval${waiting > 1 ? "s" : ""} waiting</b>` : ""}</div></div>`;
    }).join("");
    const w = WOS[state.selectedWO];
    return `<h2>Dispatch board</h2><div class="sub">Agents propose; rules or a person approve. Every answer shows which tier answered and how fresh it is.</div>
      <h3>Work orders</h3>${list}${w ? woDetail(w) : ""}`;
  }
  function woDetail(w) {
    const a = ASSETS[w.asset_id], d = w.diagnosis;
    const p1 = provFor("diagnose_issue", "supervisor"), p2 = provFor("find_technicians", "supervisor"), p3 = provFor("recommend_repair_location", "supervisor"), p4 = provFor("check_parts", "supervisor");
    const techs = w.technicians.slice(0, 3).map((c) => `<tr><td><b>${esc(c.name)}</b><div class="muted">${esc(c.technician_id)}</div></td><td>${Math.round(c.score * 100)}</td>
      <td>${c.distance_km} km<div class="muted">${c.eta_min} min</div></td><td>${c.available ? '<span class="ok">on shift</span>' : '<span class="muted">off</span>'}${c.missing_skills.length ? `<div class="bad">missing ${esc(c.missing_skills.join(", "))}</div>` : ""}</td></tr>`).join("");
    const loc = w.location;
    const parts = w.parts.lines.map((l) => `<tr><td><b>${esc(l.part_number)}</b><div class="muted">${esc(l.description)}</div></td><td>${l.qty}</td><td>${esc(l.pick_type === "van" ? "van" : l.pick_type)}<div class="muted">${esc(l.pick)}</div></td><td>${usd(l.unit_price * l.qty)}</td></tr>`).join("");
    const appr = w.approvals.map((x, i) => `<div class="appr"><div><b>${esc(x.action)}</b> <span class="muted">${esc(x.rule)}</span></div>
      ${x.outcome === "human" ? `<button class="btn small amber" data-approve="${i}">Approve · ${esc(x.approver)}</button>` : `<span class="ok">${esc(x.approver)}</span>`}</div>`).join("");
    const feed = (state.feed[w.work_order_id] || []).map((f) => `<div><span class="muted">+${(f.t / 3600).toFixed(1)}h</span> ${esc(f.text)}</div>`).join("");
    const inTransit = state.queue.filter((q) => q.wo === w.work_order_id && q.dir === "up" && q.status !== "synced").length;
    const telAge = telemetryAgeForSupervisor();
    return `<h3 style="margin-top:22px">${esc(w.work_order_id)} · ${esc(a.asset_id)}</h3>
      <div class="sub">${esc(a.category)} · ${esc(a.site_name)} · criticality ${esc(a.criticality)} · site coverage <b>${esc(a.coverage)}</b></div>
      ${!d.safe_to_run ? `<div class="safety">${d.safety_override ? "Unsafe to run: edge safety rule fired. Agents cannot override this." : "Unsafe to run: shutdown recommended."}</div>` : ""}
      <h3><span><span class="wf">W1</span> Diagnosis</span>${p1.html}</h3>${causesBlock(d.causes)}
      <h3><span><span class="wf">W2</span> Technician</span>${p2.html}</h3>
      <table class="mini"><tr><th>Technician</th><th>Score</th><th>Drive</th><th>Status</th></tr>${techs}</table>
      <div class="sub">Needs: ${esc(w.skills_required.join(", "))} · est. ${w.est_hours} h</div>
      <h3><span><span class="wf">W3</span> Repair location</span>${p3.html}</h3>
      <div class="card"><b>${loc.location === "workshop" ? `Workshop (${esc(DEPOTS[loc.workshop_id]?.city || loc.workshop_id)})` : "On site"}</b> <span class="muted">· on-site ${loc.score_on_site} vs workshop ${loc.score_workshop}</span>
        <div class="sub">${loc.factors.map((f) => `${esc(f.factor)} → ${esc(f.favors.replace("_", " "))}`).join(" · ")}</div>${loc.note ? `<div class="note">${esc(loc.note)}</div>` : ""}</div>
      <h3><span><span class="wf">W4</span> Parts</span>${p4.html}</h3>
      <table class="mini"><tr><th>Part</th><th>Qty</th><th>Source</th><th>Cost</th></tr>${parts}</table><div class="sub">Total ${usd(w.parts.total_usd)}</div>
      <h3>Approvals <span class="muted" style="font-weight:400;font-size:12px">rule-based</span></h3>${appr}
      <h3>Live telemetry ${telAge === null ? '<span class="prov none">no data</span>' : `<span class="prov edge">Edge <span class="conf">· ${fmtAge(telAge)}</span></span>`}</h3>
      ${telemetryBlock(w.asset_id, telAge, "The site gateway isn't reporting (M6). The technician falls back to guided inspection.")}
      <h3>Activity (as seen by the cloud)</h3><div class="feed">${feed}</div>
      ${inTransit ? `<div class="note">${inTransit} update${inTransit > 1 ? "s" : ""} from the field ${inTransit > 1 ? "are" : "is"} still in the technician's outbox or at the hub.</div>` : ""}`;
  }
  function approve(w, i) {
    const x = w.approvals[i];
    x.outcome = "approved"; x.approver = `${x.approver} (approved)`;
    callTool("update_work_order", "supervisor", `Approve ${x.action.toLowerCase()} for ${w.work_order_id}`);
    if (x.action === "Parts") callTool("reserve_parts", "supervisor", `Reserve parts for ${w.work_order_id}`);
    if (!w.approvals.some((y) => y.outcome === "human")) {
      w.status = "assigned"; w.assigned_technician_id = w.technicians[0].technician_id;
      state.feed[w.work_order_id].push({ t: state.simOffset, text: `Approved; assigned to ${TECHS[w.assigned_technician_id].name}` });
      api(`/api/recommendations/${w.work_order_id}/assign`, { technician_id: w.assigned_technician_id });
      enqueue("down", "P1", w.work_order_id, `Assignment ${w.work_order_id}`, "assign", { tech: w.assigned_technician_id });
      toast(`${w.work_order_id} assigned to ${TECHS[w.assigned_technician_id].name}`);
    }
    render();
  }

  // ------------------------------------------------------------------ technician
  function myJobs() {
    return D.work_orders.filter((w) => state.techView[w.work_order_id]?.assigned === state.techId && state.techView[w.work_order_id].status !== "completed");
  }
  function currentJob() {
    if (state.persona === "walkthrough") return WT_WO;
    return myJobs()[0];
  }

  function technicianPanel() {
    const t = TECHS[state.techId];
    const opts = D.technicians.map((x) => `<option value="${x.technician_id}" ${x.technician_id === state.techId ? "selected" : ""}>${esc(x.name)} · ${esc(DEPOTS[x.home_depot].city)}</option>`).join("");
    const jobs = myJobs();
    const pendingDown = state.queue.filter((q) => q.dir === "down" && q.status !== "synced" && q.payload.tech === state.techId).length;
    let body;
    if (!jobs.length) {
      body = `<div class="empty">No assigned jobs on this device.${pendingDown ? `<br>${pendingDown} new assignment waiting for a connection.` : ""}<br><span class="sub">Approve a work order in the Supervisor view, or pick another technician.</span></div>`;
    } else {
      const w = jobs[0];
      const outN = state.queue.filter((q) => q.dir === "up" && q.status !== "synced").length;
      const tabs = [["plan", "Repair plan"], ["diagnose", "Diagnose"], ["pack", "Mission pack"], ["parts", "Parts"], ["telemetry", "Live data"], ["closeout", "Close out"], ["outbox", `Outbox (${outN})`]];
      body = `${jobCard(w)}<div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button class="tab ${state.techTab === k ? "active" : ""}" data-tab="${k}">${esc(l)}</button>`).join("")}</div>${techTab(w)}`;
    }
    return `<h2>My jobs</h2><div class="row" style="margin:6px 0 4px"><select id="tech-select" aria-label="Technician" style="flex:1">${opts}</select></div>
      <div class="sub">Van ${esc(t.van_id)} · ${esc(t.skills.join(", "))}</div>${body}`;
  }
  function jobCard(w) {
    const a = ASSETS[w.asset_id];
    const c = w.technicians.find((x) => x.technician_id === state.techId) || w.technicians[0];
    return `<div class="card"><div class="row"><b>${esc(w.work_order_id)}</b><span class="pill pri-${w.priority}">${esc(w.priority)}</span></div>
      <div>${esc(w.title)}</div><div class="sub">${esc(a.asset_id)} · ${esc(a.model)} · ${c.distance_km} km, about ${c.eta_min} min drive</div>
      <div class="sub">${esc(a.access_notes)}${a.hazards.length ? ` · <b>Hazards:</b> ${esc(a.hazards.join("; "))}` : ""}</div></div>
      ${!w.diagnosis.safe_to_run ? `<div class="safety">Do not run this unit. ${w.diagnosis.safety_override ? "The edge safety rule tripped." : "Shutdown recommended."}</div>` : ""}`;
  }

  function planBlock(w, interactive = true) {
    const cached = state.plans[w.work_order_id];
    if (!cached) {
      loadPlan(w.work_order_id, state.persona === "walkthrough" ? "walkthrough" : "technician").then(render);
      return `<div class="empty">Loading the repair plan…</div>`;
    }
    const { plan, source, at } = cached;
    const local = state.stepLocal[w.work_order_id] || {};
    const srcChip = source === "db" ? `<span class="prov cloud">Repair DB <span class="conf">· v${plan.version} · ${fmtAge(Math.max(0, state.simOffset - at))}</span></span>`
      : `<span class="prov field">Mission pack copy <span class="conf">· ${state.api ? "synced at depot" : "embedded demo data"}</span></span>`;
    const phases = ["safety", "verify", "repair", "test", "closeout"];
    const PH = { safety: "Lockout / tagout", verify: "Verify the diagnosis", repair: "Repair", test: "Test run", closeout: "Close out" };
    const steps = phases.map((ph) => {
      const ss = plan.steps.filter((s) => s.phase === ph);
      if (!ss.length) return "";
      return `<div class="phase"><div class="phase-h">${PH[ph]}</div>${ss.map((s) => {
        const st = local[s.seq] || (s.status === "done" ? "synced" : null);
        return `<label class="check step ${st ? "done" : ""}"><input type="checkbox" data-step="${s.seq}" ${st ? "checked disabled" : ""} ${interactive ? "" : "disabled"}>
          <span>${esc(s.instruction)}${st ? `<span class="step-st ${st}">${st === "synced" ? "saved to DB" : st === "hub" ? "at hub" : "queued offline"}</span>` : ""}</span></label>`;
      }).join("")}</div>`;
    }).join("");
    const done = plan.steps.filter((s) => local[s.seq] || s.status === "done").length;
    const refs = plan.references.map((r) => `<details><summary>${esc(r.kind === "manual" ? "Manual" : r.kind === "asset_repair" ? "This asset" : "Similar fix")} · ${esc(r.title)}</summary><pre>${esc(r.detail)}</pre></details>`).join("");
    return `<h3><span>Repair recommendation</span>${srcChip}</h3>
      <div class="card"><b>${esc(plan.cause_description)}</b> <span class="muted">${esc(plan.cause_code)}</span>
        <div class="sub">${esc(plan.generated_by)} · est. ${plan.est_hours} h · ${plan.repair_location === "workshop" ? "workshop job" : "on site"}</div>
        <div class="progress"><span style="width:${Math.round((done / plan.steps.length) * 100)}%"></span></div>
        <div class="sub">${done} of ${plan.steps.length} steps done</div></div>
      ${steps}
      <h3>References in this plan</h3>${refs || '<div class="sub">None</div>'}`;
  }

  function techTab(w) {
    const a = ASSETS[w.asset_id], tab = state.techTab;
    if (tab === "plan") return planBlock(w);
    if (tab === "diagnose") {
      const p = provFor("diagnose_issue", "technician");
      if (state.sensorsLost) {
        const tr = (D.manuals[a.model] || []).filter((m) => m.title.startsWith("Troubleshooting"));
        const symOf = (m) => (m.text.match(/Typical symptoms: ([^.]*)\./) || ["", ""])[1].split("; ").filter(Boolean);
        const syms = [...new Set(tr.flatMap(symOf))];
        const sel = state.inspection[w.work_order_id] || new Set();
        const ranked = tr.map((m) => ({ title: m.title.replace("Troubleshooting: ", ""), code: (m.text.match(/Fault code (\S+)\./) || ["", ""])[1], hit: symOf(m).filter((x) => sel.has(x)).length })).sort((x, y) => y.hit - x.hit);
        return `<h3><span><span class="wf">W1</span> Guided inspection</span><span class="prov field">Device <span class="conf">· sensors lost</span></span></h3>
          <div class="note">No live data from the site gateway (M6). Tick what you observe; the device ranks causes from the mission pack.</div>
          ${syms.map((s) => `<label class="check"><input type="checkbox" data-sym="${esc(s)}" ${sel.has(s) ? "checked" : ""}><span>${esc(s)}</span></label>`).join("")}
          <h3>Likely causes</h3>${ranked.map((r) => `<div class="cause"><span>${esc(r.title)} <span class="muted">${esc(r.code)}</span></span><div class="bar"><span style="width:${Math.min(r.hit * 34, 100)}%"></span></div><b>${r.hit}</b></div>`).join("")}`;
      }
      return `<h3><span><span class="wf">W1</span> Diagnosis</span>${p.html}</h3><div class="sub">${esc(p.why)}</div>${causesBlock(w.diagnosis.causes)}
        <h3>Evidence</h3>${w.diagnosis.evidence.map((e) => `<div class="sub">• ${esc(e)}</div>`).join("") || '<div class="sub">No alarms yet</div>'}`;
    }
    if (tab === "pack") {
      const hist = (D.history[a.asset_id] || []).slice(0, 5);
      return `<div class="note">Mission pack synced at the depot. Fully available offline.</div>
        <h3>Manual: ${esc(a.model)}</h3>${(D.manuals[a.model] || []).map((m) => `<details><summary>${esc(m.title)}</summary><pre>${esc(m.text)}</pre></details>`).join("")}
        <h3>Past repairs on ${esc(a.asset_id)}</h3>${hist.length ? hist.map((h) => `<div class="card"><div class="row"><b>${esc(h.cause_code)}</b><span class="muted">${esc(h.date)}</span></div><div class="sub">${esc(h.notes)} · ${h.labor_hours} h · ${h.first_time_fix ? '<span class="ok">first-time fix</span>' : '<span class="bad">return visit</span>'}</div></div>`).join("") : '<div class="sub">No previous repairs</div>'}`;
    }
    if (tab === "parts") {
      const p = provFor("check_parts", "technician"), van = state.van[state.techId];
      const rows = w.parts.lines.map((l) => { const have = van[l.part_number] || 0; return `<tr><td><b>${esc(l.part_number)}</b><div class="muted">${esc(l.description)}</div></td><td>${l.qty}</td><td class="${have >= l.qty ? "ok" : "bad"}">${have}</td><td><button class="btn small ghost" data-use="${esc(l.part_number)}" ${have ? "" : "disabled"}>Use 1</button></td></tr>`; }).join("");
      const missing = w.parts.lines.filter((l) => (van[l.part_number] || 0) < l.qty);
      return `<h3><span><span class="wf">W4</span> Parts for this job</span>${p.html}</h3><div class="sub">${esc(p.why)}</div>
        <table class="mini"><tr><th>Part</th><th>Need</th><th>In van</th><th></th></tr>${rows}</table>
        ${missing.length ? `<div class="note">Not in the van: ${missing.map((l) => `${esc(l.part_number)} from ${esc(l.pick_type)} ${esc(l.pick)}`).join(", ")}.</div>` : ""}
        <h3>Van stock</h3><table class="mini">${Object.entries(van).map(([pn, q]) => `<tr><td>${esc(pn)}</td><td>${q}</td></tr>`).join("")}</table>`;
    }
    if (tab === "telemetry") {
      return `<h3>Live data <span class="prov edge">Edge <span class="conf">· local link</span></span></h3><div class="sub">Read straight from the site gateway over Wi-Fi/BLE, so it works with no WAN.</div>
        ${telemetryBlock(a.asset_id, state.sensorsLost ? null : 5, "The site gateway isn't reporting (M6). Use the guided inspection on the Diagnose tab and record readings by hand.")}`;
    }
    if (tab === "closeout") {
      return `<h3><span><span class="wf">W6</span> Close out</span></h3>
        <label class="sub" for="co-cause">Confirmed cause</label>
        <select id="co-cause" style="width:100%;margin:4px 0 8px">${w.diagnosis.causes.map((c) => `<option value="${esc(c.cause_code)}">${esc(c.description)} (${esc(c.cause_code)})</option>`).join("")}</select>
        <label class="sub" for="co-notes">Findings</label><textarea id="co-notes" rows="3" style="width:100%;margin:4px 0 8px" placeholder="What you found and did"></textarea>
        <div class="row" style="justify-content:flex-start;gap:8px;flex-wrap:wrap"><button class="btn ghost" id="co-photo">Attach photo (3.2 MB)</button><button class="btn ghost" id="co-findings">Save findings</button><button class="btn amber" id="co-complete">Complete job</button></div>
        <div class="sub" style="margin-top:8px">Findings, steps and status are P1 and go out first. Photos are P4 and wait for a good link (M0).</div>`;
    }
    const items = state.queue.filter((q) => q.dir === "up").slice().reverse();
    return `<h3>Outbox <span class="muted" style="font-weight:400;font-size:12px">sent in priority order when the link allows</span></h3>
      ${items.length ? items.map((q) => `<div class="outbox-item"><span class="prio ${q.prio}" title="${PRIO_LABEL[q.prio]}">${q.prio}</span><span>${esc(q.text)}<div class="muted">${esc(q.wo)}</div></span>
        <span class="${q.status === "synced" ? "q-synced" : q.status === "hub" ? "q-hub" : "q-queued"}">${q.status === "synced" ? "synced" : q.status === "hub" ? "at hub" : "queued"}</span></div>`).join("") : '<div class="empty">Nothing recorded yet</div>'}`;
  }

  // Technician actions (also used by the walkthrough)
  function record(who, prio, wo, text, kind, payload = {}) {
    const tool = kind === "step" ? "repair_db.update_step" : kind === "complete" ? "repair_db.outcome" : kind === "photo" ? "update_work_order" : "update_work_order";
    const p = callTool(tool, who, text);
    const q = enqueue("up", prio, wo, text, kind, payload);
    if (kind === "step") (state.stepLocal[wo] ||= {})[payload.seq] = q.status === "synced" ? "synced" : q.status === "hub" ? "hub" : "queued";
    return { p, q };
  }
  function doStep(who, wo, seqNo, techId) {
    const plan = state.plans[wo]?.plan; const s = plan?.steps.find((x) => x.seq === seqNo);
    if (!s || (state.stepLocal[wo] || {})[seqNo]) return;
    const prio = s.phase === "safety" ? "P0" : "P1";
    record(who, prio, wo, `Step ${seqNo} done: ${s.instruction.slice(0, 60)}${s.instruction.length > 60 ? "…" : ""}`, "step", { seq: seqNo, by: techId });
  }
  function completeJob(who, wo, cause, notes, techId) {
    record(who, "P1", wo, `Job complete, cause ${cause}`, "complete", { cause, notes, by: techId });
    state.techView[wo] = { ...(state.techView[wo] || {}), status: "completed", assigned: techId };
  }

  // ------------------------------------------------------------------ assistant
  const INTENTS = [
    ["safety", /safe|restart|run it|start it/i],
    ["diagnose", /wrong|cause|diagnos|fault|problem|issue/i],
    ["telemetry", /reading|live|telemetry|temperature|pressure|vibration|current|dew|sensor/i],
    ["parts", /part|stock|spare|van|van|filter|seal|kit/i],
    ["techs", /who|technician|help me|dispatch|assign|colleague/i],
    ["location", /where|workshop|on.?site|location/i],
    ["procedure", /how|fix|procedure|step|manual|repair|plan/i],
    ["history", /history|before|past|last time|similar/i],
    ["status", /sync|outbox|offline|queue|connection|network|signal/i],
  ];
  function repairDone(w) {
    const plan = state.plans[w.work_order_id]?.plan, local = state.stepLocal[w.work_order_id] || {};
    return !!plan && plan.steps.filter((s) => s.phase === "repair").every((s) => local[s.seq] || s.status === "done");
  }
  function contextWO(who) { return who === "supervisor" ? WOS[state.selectedWO] : currentJob(); }

  function ask(q, who) {
    const w = contextWO(who);
    const via = "assistant";
    if (!w) return pushChat(who, q, "There's no job selected. Pick a work order first.", null);
    const intent = (INTENTS.find(([, re]) => re.test(q)) || ["help"])[0];
    const a = ASSETS[w.asset_id], d = w.diagnosis, top = d.causes[0];
    let tool = null, answer = "";
    if (intent === "diagnose" || intent === "safety") {
      tool = callTool("diagnose_issue", who, q, { via });
      if (state.sensorsLost && isField(who)) answer = `No live data from the gateway. From the mission pack, start by checking: ${top.description.toLowerCase()} (${top.cause_code}). Tick symptoms on the Diagnose tab and I'll re-rank.`;
      else if (intent === "safety" && isField(who) && repairDone(w)) answer = `Yes. The repair steps are done: remove your locks in reverse order, restart, and watch ${Object.keys(D.telemetry[a.asset_id].thresholds).slice(0, 2).join(" and ")} for 15 minutes (the test step).`;
      else if (intent === "safety") answer = d.safe_to_run ? `Yes, it can run while you prepare, but plan the repair: likely ${top.description.toLowerCase()}. After the fix, restart only once the lockout steps are reversed and the test step is done.` : `No. ${d.safety_override ? "The edge safety rule tripped, and nobody can override that." : "Shutdown is recommended."} Keep it locked out until the repair and test steps are done.`;
      else answer = `Most likely ${top.description.toLowerCase()} (${Math.round(top.probability * 100)}%), then ${d.causes[1].description.toLowerCase()} (${Math.round(d.causes[1].probability * 100)}%). ${d.safe_to_run ? "Safe to keep running for now." : "Do not run it."} Evidence: ${d.evidence[0] || "reported symptoms"}.`;
    } else if (intent === "telemetry") {
      tool = callTool("get_live_telemetry", who, q, { via });
      if (tool.status === "failed") answer = "The site gateway isn't reporting, so there are no live readings. Take manual readings and log them in your findings.";
      else {
        const T = D.telemetry[a.asset_id];
        answer = T.series.slice(0, 4).map((s) => { const th = T.thresholds[s.signal], v = s.points.at(-1).value; const bad = th.warn != null && (th.low_is_bad ? v <= th.warn : v >= th.warn); return `${s.signal} ${v.toFixed(1)} ${s.unit}${bad ? " (over limit)" : ""}`; }).join("; ") + `. ${tool.status === "stale" ? "These are last known values." : ""}`;
      }
    } else if (intent === "parts") {
      tool = callTool("check_parts", who, q, { via });
      const van = isField(who) ? state.van[state.techId] : {};
      answer = w.parts.lines.map((l) => isField(who) ? `${l.part_number} (${l.description}): ${(van[l.part_number] || 0) >= l.qty ? "in your van" : `not in your van, ${tool.tier === "field" ? "can't check depot stock offline" : `get it from ${l.pick_type} ${l.pick}`}`}` : `${l.part_number}: ${l.qty} from ${l.pick_type} ${l.pick}`).join(". ") + ".";
      if (isField(who) && w.parts.lines.some((l) => (van[l.part_number] || 0) < l.qty)) callTool("reserve_parts", who, `Reserve missing parts for ${w.work_order_id}`, { via });
    } else if (intent === "techs") {
      tool = callTool("find_technicians", who, q, { via });
      const others = w.technicians.filter((c) => !isField(who) || c.technician_id !== state.techId);
      answer = tool.status === "failed" ? `I can't reach dispatch from here. Call the dispatcher; the last ranking had ${others[0].name} first.` : others.slice(0, 2).map((c) => `${c.name} (${c.eta_min} min away${c.missing_skills.length ? `, missing ${c.missing_skills.join(", ")}` : ""})`).join(" or ") + ".";
    } else if (intent === "location") {
      tool = callTool("recommend_repair_location", who, q, { via });
      answer = `${w.location.location === "workshop" ? "Take it to the workshop" : "Repair it on site"}: ${w.location.factors.slice(0, 3).map((f) => f.factor.toLowerCase()).join(", ")}.${w.location.note ? " " + w.location.note + "." : ""}`;
    } else if (intent === "procedure") {
      tool = callTool("search_knowledge", who, q, { via });
      callTool("repair_db.get_plan", who, `Repair plan for ${w.work_order_id}`, { via });
      answer = `Lockout first (6 steps), then: ${w.procedure.map((s, i) => `${i + 1}) ${s}`).join(" ")} The full plan with checkboxes is on the Repair plan tab.`;
    } else if (intent === "history") {
      tool = callTool("search_knowledge", who, q, { via });
      const h = (D.history[a.asset_id] || []).slice(0, 2);
      answer = h.length ? h.map((r) => `${r.date}: ${r.cause_code}, ${r.labor_hours} h, ${r.first_time_fix ? "fixed first time" : "needed a return visit"}`).join(". ") + "." : "No earlier repairs on this unit.";
    } else if (intent === "status") {
      const p = callTool("local_status", who, q, { via });
      const n = state.queue.filter((x) => x.status !== "synced").length;
      answer = `You're in ${state.mode} (${mode().name}). ${n ? `${n} update${n > 1 ? "s" : ""} waiting; safety (P0) and job updates (P1) go first when the link allows, photos last.` : "Everything is synced."}`;
      return pushChat(who, q, answer, p, null);
    } else {
      const p = callTool("local_status", who, q, { via });
      return pushChat(who, q, "I can help with: what's wrong, is it safe, live readings, parts, who else could help, where to repair, how to fix it, past repairs, and sync status.", p, null);
    }
    const comp = callTool("compose_answer", who, `Write answer: "${q}"`, { via });
    return pushChat(who, q, answer, comp, tool);
  }
  function pushChat(who, q, a, comp, tool) {
    const ms = (comp?.ms || 0) + (tool?.ms || 0), tok = (comp?.tin || 0) + (comp?.tout || 0) + (tool?.tin || 0) + (tool?.tout || 0);
    const foot = comp ? `${TIER_NAME[comp.tier]}${comp.model ? ` · ${comp.model}` : ""} · ${fmtMs(ms)} · ${fmtTok(tok)} tokens` : "";
    const msg = { who, q, a, foot, tier: comp?.tier || "field" };
    state.chat.push(msg);
    renderAssistant();
    return msg;
  }
  function suggestions() {
    if (state.persona === "supervisor") return ["What's wrong with it?", "Who should go?", "Do we have the parts?", "On site or workshop?"];
    return ["What's wrong with this unit?", "Show me live readings", "Do I have the parts?", "How do I fix it?", "Is it safe to restart?", "What's my sync status?"];
  }
  function renderAssistant() {
    const box = $("#assistant");
    box.hidden = !state.assistantOpen;
    $("#ask-fab").hidden = state.assistantOpen;
    if (!state.assistantOpen) return;
    const w = contextWO(state.persona);
    $("#as-context").textContent = w ? `${w.work_order_id} · ${ASSETS[w.asset_id].model} · ${PERSONA_NAME[state.persona]} · ${state.mode}` : "No job selected";
    const msgs = state.chat.filter((m) => m.who === state.persona || (state.persona === "technician" && m.who === "walkthrough")).slice(-8);
    $("#as-msgs").innerHTML = msgs.length ? msgs.map((m) => `<div class="msg q">${esc(m.q)}</div><div class="msg a">${esc(m.a)}${m.foot ? `<div class="foot"><span class="dot-t ${m.tier}"></span>${esc(m.foot)}</div>` : ""}</div>`).join("")
      : `<div class="sub" style="padding:8px 2px">Ask about the selected job. Each answer shows where it ran and what it cost; every request appears in the live panel.</div>`;
    $("#as-msgs").scrollTop = 1e6;
    $("#as-chips").innerHTML = suggestions().map((s) => `<button class="as-chip" data-ask="${esc(s)}">${esc(s)}</button>`).join("");
  }

  // ------------------------------------------------------------------ live panel
  function renderLive(flashId) {
    const L = state.log;
    const tot = { n: L.length, ms: 0, cloud: 0, hub: 0, field: 0, local: 0 };
    for (const e of L) {
      tot.ms += e.ms;
      const tk = e.tin + e.tout;
      if (e.tier in tot) tot[e.tier] += tk;
      if (e.tier !== "cloud" && e.tier !== "none") tot.local += 1;
    }
    const pct = tot.n ? Math.round((tot.local / tot.n) * 100) : 0;
    const counts = { cloud: 0, hub: 0, field: 0, edge: 0, none: 0 };
    L.forEach((e) => (counts[e.tier] = (counts[e.tier] || 0) + 1));
    const bar = Object.entries(counts).filter(([, n]) => n).map(([t, n]) => `<span class="lb ${t}" style="flex:${n}" title="${TIER_NAME[t]}: ${n}"></span>`).join("");
    $("#live-totals").innerHTML = `<span><b>${tot.n}</b> requests</span><span><b>${fmtMs(tot.ms)}</b> total</span>
      <span>tokens: <b class="t-cloud">${fmtTok(tot.cloud)}</b> cloud · <b class="t-hub">${fmtTok(tot.hub)}</b> hub · <b class="t-field">${fmtTok(tot.field)}</b> device</span>
      <span><b>${pct}%</b> without the cloud</span><span class="lbar" aria-hidden="true">${bar}</span>`;
    if (!state.liveOpen) return;
    const who = (e) => (e.who === "outbox" ? "Outbox" : PERSONA_NAME[e.who] || e.who) + (e.via ? " · assistant" : "");
    $("#live-rows").innerHTML = L.slice(-60).reverse().map((e) => `<div class="live-row ${e.id === flashId ? "flash" : ""} st-${e.status}">
      <span class="muted">+${(e.t / 3600).toFixed(1)}h</span><span>${esc(who(e))}</span><span class="req">${esc(e.request)}</span>
      <span class="mono">${esc(e.tool)}</span><span><span class="prov ${e.tier}">${TIER_NAME[e.tier]}${e.model ? ` <span class="conf">· ${esc(e.model)}</span>` : ""}</span>${e.status === "queued" ? ' <span class="q-queued">queued</span>' : e.status === "failed" ? ' <span class="bad">failed</span>' : e.status === "stale" ? ' <span class="q-queued">stale</span>' : ""}</span>
      <span class="why">${esc(e.why)}</span><span class="r">${fmtMs(e.ms)}</span><span class="r">${e.tin + e.tout ? `${fmtTok(e.tin)} in / ${fmtTok(e.tout)} out` : '<span class="muted">0</span>'}</span></div>`).join("")
      || `<div class="empty">No requests yet. Pick a work order, open a tab, or ask the assistant.</div>`;
  }

  // ------------------------------------------------------------------ walkthrough persona
  const WT = { idx: -1, running: false, notes: {}, auto: false };
  function wtSteps() {
    const w = WT_WO, a = ASSETS[w.asset_id], t = TECHS[w.assigned_technician_id], n = firstName(t.technician_id);
    const van = state.van[t.technician_id];
    const missing = w.parts.lines.filter((l) => (van[l.part_number] || 0) < l.qty);
    const S = (time, mode, lost, pos, title, story, run) => ({ time, mode, lost, pos, title, story, run });
    const who = "walkthrough", wo = w.work_order_id;
    const say = async (i, q) => { const m = ask(q, who); (WT.notes[i] ||= []).push({ q, a: m.a, foot: m.foot }); await sleep(450); };
    const did = (i, text) => (WT.notes[i] ||= []).push({ did: text });
    const plan = () => state.plans[wo].plan;
    const stepsOf = (ph) => plan().steps.filter((s) => s.phase === ph);
    return [
      S("07:30", "M0", false, 0, "At the depot", `${n} gets ${wo} on the tablet: ${a.category} at ${a.site_name}. Before leaving, the mission pack and the repair recommendation sync over depot Wi-Fi.`, async (i) => {
        await loadPlan(wo, who, `Download repair plan ${wo}`); did(i, `Repair plan v${plan().version} loaded from the ${state.plans[wo].source === "db" ? "repair DB" : "mission pack"} (${plan().steps.length} steps)`);
        callTool("sync_mission_pack", who, `Mission pack for ${a.asset_id}: manuals, history, plan (4.2 MB)`); did(i, "Mission pack downloaded (P3, depot Wi-Fi)"); await sleep(300);
        await say(i, "What's wrong with this unit?");
      }),
      S("08:15", "M1", false, 0.35, "On the highway, weak signal", `One bar of LTE. ${n} checks parts on the way; only small messages go out on a slow link.`, async (i) => {
        await say(i, "Do I have the parts?");
        did(i, missing.length ? `Missing ${missing.map((l) => l.part_number).join(", ")}: reserved at ${missing[0].pick}` : "All parts are in the van");
      }),
      S("09:20", "M2", false, 0.8, "Approach road, signal comes and goes", `Coverage drops in and out. The device answers first; the cloud is used only when a window opens.`, async (i) => {
        await say(i, "Who else could help if I get stuck?");
        await say(i, "How do I fix it?");
      }),
      S("09:45", "M5", false, 1, "On site, no coverage", `No WAN at all. ${n} reads the compressor over the gateway's local link and locks it out, following the plan from the database copy.`, async (i) => {
        await say(i, "Show me live readings");
        for (const s of stepsOf("safety")) { doStep(who, wo, s.seq, t.technician_id); await sleep(150); }
        did(i, `Lockout steps 1–${stepsOf("safety").length} done (P0, queued offline)`);
      }),
      S("10:30", "M5", false, 1, "Repair, still offline", `${n} confirms the diagnosis, does the repair and test-runs the compressor, all from the plan in the mission pack.`, async (i) => {
        for (const s of [...stepsOf("verify"), ...stepsOf("repair")]) { doStep(who, wo, s.seq, t.technician_id); await sleep(150); }
        for (const l of w.parts.lines) if ((van[l.part_number] || 0) > 0) { van[l.part_number] -= 1; record(who, "P1", wo, `Used 1 × ${l.part_number} from van`, "parts"); }
        await say(i, "Is it safe to restart?");
        for (const s of stepsOf("test")) doStep(who, wo, s.seq, t.technician_id);
        did(i, "Diagnosis confirmed, repair and test-run steps done (P1, queued)");
      }),
      S("11:00", "M5", false, 1, "Close out on site", `Findings, a photo and the completed job are recorded. Nothing is lost: it all waits in the outbox.`, async (i) => {
        record(who, "P1", wo, `Findings: ${w.diagnosis.causes[0].cause_code} confirmed, replaced parts, test run OK`, "findings");
        record(who, "P4", wo, "Photo of the replaced part (3.2 MB)", "photo");
        for (const s of stepsOf("closeout")) doStep(who, wo, s.seq, t.technician_id);
        completeJob(who, wo, w.diagnosis.causes[0].cause_code, "Repaired per plan, test run OK", t.technician_id);
        await say(i, "What's my sync status?");
      }),
      S("12:10", "M2", false, 0.6, "Driving out, a window opens", `The first coverage window sends safety records and job updates first. The photo waits for a good link.`, async (i) => {
        syncTick(false, true); await sleep(400); syncTick(false, true);
        did(i, `${state.queue.filter((q) => q.status === "synced").length} updates written to the repair DB; photo still waiting (P4)`);
      }),
      S("13:00", "M0", false, 0.1, "Back in coverage", `Full connectivity. The photo uploads, the supervisor sees ${wo} completed, and the repair outcome is in the database for the next technician.`, async (i) => {
        syncTick(); await sleep(300);
        await loadPlan(wo, who, `Refresh plan ${wo} after sync`);
        did(i, `Repair DB now shows ${plan().steps.filter((s) => s.status === "done").length || plan().steps.length} steps done, status ${plan().status || "completed"}`);
      }),
    ];
  }
  let WT_STEPS = null;
  async function runWtStep() {
    if (WT.running) return;
    WT_STEPS ||= wtSteps();
    if (WT.idx >= WT_STEPS.length - 1) return;
    WT.running = true;
    WT.idx += 1;
    const s = WT_STEPS[WT.idx];
    state.techId = WT_WO.assigned_technician_id;
    state.simOffset = WT.idx * 1800 + 3600;
    state.sensorsLost = s.lost;
    const t = TECHS[state.techId], a = ASSETS[WT_WO.asset_id];
    state.techPos = [t.lat + (a.lat - t.lat) * s.pos, t.lon + (a.lon - t.lon) * s.pos];
    setMode(s.mode, true);
    render();
    try { await s.run(WT.idx); } finally { WT.running = false; }
    render();
    if (WT.auto && WT.idx < WT_STEPS.length - 1) { await sleep(1200); runWtStep(); } else WT.auto = false;
  }
  function walkthroughPanel() {
    WT_STEPS ||= wtSteps();
    const w = WT_WO, t = TECHS[w.assigned_technician_id];
    const steps = WT_STEPS.map((s, i) => {
      const notes = (WT.notes[i] || []).map((n) => n.did ? `<div class="wt-did">✓ ${esc(n.did)}</div>` : `<div class="msg q">${esc(n.q)}</div><div class="msg a">${esc(n.a)}<div class="foot">${esc(n.foot)}</div></div>`).join("");
      const m = MODES[s.mode];
      return `<div class="wt-step ${i === WT.idx ? "current" : i < WT.idx ? "done" : ""}">
        <div class="row"><b>${i + 1}. ${esc(s.title)}</b><span><span class="muted">${s.time}</span> <span class="pill" style="background:${m.color};color:${m.dark ? "var(--text)" : "#fff"}">${s.mode}</span></span></div>
        <div class="sub">${esc(s.story)}</div>${i <= WT.idx ? notes : ""}</div>`;
    }).join("");
    const done = WT.idx >= WT_STEPS.length - 1;
    return `<h2>${esc(t.name)} repairs ${esc(w.work_order_id)}</h2>
      <div class="sub">A day in the field: the assigned technician follows the repair recommendation from the database, through a dead zone and back. Every request shows up in the live panel.</div>
      <div class="row wt-controls"><button class="btn amber" id="wt-next" ${WT.running || done ? "disabled" : ""}>${WT.idx < 0 ? "Start" : "Next step"}</button>
        <button class="btn ghost" id="wt-auto" ${WT.running || done ? "disabled" : ""}>Play all</button><button class="btn ghost" id="wt-restart">Restart demo</button></div>
      ${jobCard(w)}${steps}
      ${WT.idx >= 0 ? `<h3>Live repair plan</h3>${state.plans[w.work_order_id] ? planBlock(w, false) : ""}` : ""}`;
  }

  // ------------------------------------------------------------------ banner + controls
  function banner() {
    const m = mode();
    const ln = (label, st) => `<span>${label}: <span class="${st === "down" ? "link-down" : st === "flaky" ? "link-flaky" : "link-up"}">${st}</span></span>`;
    const queued = state.queue.filter((q) => q.status !== "synced").length;
    $("#mode-banner").style.background = `color-mix(in srgb, ${m.color} 14%, white)`;
    $("#mode-banner").innerHTML = `<span class="badge" style="background:${m.color};${m.dark ? "color:var(--text)" : ""}">${state.mode} ${esc(m.name)}</span>
      ${state.sensorsLost ? '<span class="badge" style="background:var(--m6)">M6 Sensors lost</span>' : ""}<span>${esc(m.desc)}${state.sensorsLost ? "; site gateway not reporting" : ""}.</span>
      <span class="links">${ln("Device→cloud", m.links.cloud)}${ln("Device→hub", m.links.hub)}${ln("Edge→cloud", m.links.edgeCloud)}${ln("Cloud AI", m.links.llm)}</span>
      ${queued ? `<span><b>${queued}</b> message${queued > 1 ? "s" : ""} waiting to sync</span>` : ""}
      <span class="api-chip ${state.api ? "on" : ""}">${state.api ? "Repair DB connected" : "Repair DB: embedded data"}</span>`;
    $("#mode-chips").innerHTML = Object.entries(MODES).map(([k, v]) => `<button class="mode-chip ${k === state.mode ? "active" : ""} ${v.dark ? "dark-text" : ""}" style="background:${v.color}" data-mode="${k}" title="${esc(v.desc)}">${k}</button>`).join("");
    $("#m6").checked = state.sensorsLost;
    $("#sim-clock").textContent = fmtTime(simNow());
  }
  function setMode(m, fromScenario = false) {
    const on = (x) => ["up", "slow", "flaky"].includes(MODES[x].links.cloud);
    const was = on(state.mode);
    state.mode = m;
    if (was && !on(m)) state.offlineSince = state.simOffset;
    if (on(m) && m !== "M2") state.offlineSince = null;
    if (!fromScenario) stopScenario();
    syncTick();
    render();
  }
  function setPersona(p) {
    state.persona = p;
    for (const b of document.querySelectorAll(".persona-btn")) b.classList.toggle("active", b.dataset.persona === p);
    if (p === "walkthrough") state.techId = WT_WO.assigned_technician_id;
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
  function stopScenario() { state.playing = false; clearInterval(state.timer); $("#scenario-play").textContent = "Play"; }
  function playScenario() {
    const s = D.scenarios.find((x) => x.name === state.scenario);
    if (!s) return toast("Pick a scenario first");
    if (state.playing) return stopScenario();
    if (state.scenarioT >= s.duration_s - 1) state.scenarioT = 0;
    state.playing = true; $("#scenario-play").textContent = "Pause";
    const stepS = Math.max(300, s.duration_s / 120);
    state.timer = setInterval(() => {
      state.scenarioT += stepS; state.simOffset += stepS;
      if (state.scenarioT >= s.duration_s) { state.scenarioT = s.duration_s - 1; stopScenario(); toast("Scenario finished"); }
      const seg = [...s.segments].reverse().find((g) => g.start_s <= state.scenarioT);
      $("#scenario-note").textContent = `${(state.scenarioT / 3600).toFixed(1)} h · ${seg.note || MODES[seg.mode].name}`;
      if (seg.mode !== state.mode || seg.telemetry_lost !== state.sensorsLost) { state.sensorsLost = seg.telemetry_lost; setMode(seg.mode, true); }
      else { syncTick(); banner(); drawScenarioBar(); }
    }, 250);
  }

  // ------------------------------------------------------------------ render + events
  function render() {
    banner(); kpis(); drawScenarioBar();
    const panel = $("#panel"), top = panel.scrollTop;
    panel.innerHTML = state.persona === "supervisor" ? supervisorPanel() : state.persona === "technician" ? technicianPanel() : walkthroughPanel();
    panel.scrollTop = top;
    if (state.persona === "walkthrough") panel.querySelector(".wt-step.current")?.scrollIntoView({ block: "nearest" });
    drawMap(); renderAssistant(); renderLive();
  }
  const TAB_TOOL = { plan: "repair_db.get_plan", diagnose: "diagnose_issue", pack: "search_knowledge", parts: "check_parts", telemetry: "get_live_telemetry" };

  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-persona],[data-mode],[data-wo],[data-approve],[data-tab],[data-use],[data-ask],#co-photo,#co-findings,#co-complete,#scenario-play,#ask-fab,#as-close,#live-toggle,#live-clear,#wt-next,#wt-auto,#wt-restart");
    if (!t) return;
    if (t.dataset.persona) return setPersona(t.dataset.persona);
    if (t.dataset.mode) return setMode(t.dataset.mode);
    if (t.dataset.wo) return selectWO(t.dataset.wo);
    if (t.dataset.approve) return approve(WOS[state.selectedWO], Number(t.dataset.approve));
    if (t.dataset.tab) {
      state.techTab = t.dataset.tab;
      const w = myJobs()[0];
      if (TAB_TOOL[t.dataset.tab] && w) {
        if (t.dataset.tab === "plan") loadPlan(w.work_order_id, "technician").then(render);
        else callTool(TAB_TOOL[t.dataset.tab], "technician", `Open ${t.textContent.trim()} for ${w.work_order_id}`);
      }
      return render();
    }
    if (t.dataset.use) { const pn = t.dataset.use, w = myJobs()[0]; state.van[state.techId][pn] -= 1; record("technician", "P1", w.work_order_id, `Used 1 × ${pn} from van`, "parts"); return render(); }
    if (t.dataset.ask) { ask(t.dataset.ask, state.persona); return render(); }
    if (t.id === "co-photo") { const w = myJobs()[0]; record("technician", "P4", w.work_order_id, "Photo of failed component (3.2 MB)", "photo"); return render(); }
    if (t.id === "co-findings") { const w = myJobs()[0]; const notes = $("#co-notes").value.trim(); record("technician", "P1", w.work_order_id, `Findings: ${$("#co-cause").value}${notes ? ` · ${notes}` : ""}`, "findings"); return render(); }
    if (t.id === "co-complete") { const w = myJobs()[0]; completeJob("technician", w.work_order_id, $("#co-cause").value, $("#co-notes").value.trim(), state.techId); state.techTab = "plan"; return render(); }
    if (t.id === "scenario-play") return playScenario();
    if (t.id === "ask-fab") { state.assistantOpen = true; renderAssistant(); $("#as-input").focus(); return; }
    if (t.id === "as-close") { state.assistantOpen = false; return renderAssistant(); }
    if (t.id === "live-toggle") { state.liveOpen = !state.liveOpen; $("#live").classList.toggle("collapsed", !state.liveOpen); t.setAttribute("aria-expanded", state.liveOpen); setTimeout(() => map.invalidateSize(), 50); return renderLive(); }
    if (t.id === "live-clear") { state.log = []; return renderLive(); }
    if (t.id === "wt-next") return runWtStep();
    if (t.id === "wt-auto") { WT.auto = true; return runWtStep(); }
    if (t.id === "wt-restart") return location.reload();
  });
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t.id === "tech-select") { state.techId = t.value; state.techTab = "plan"; render(); focusMap(); }
    else if (t.id === "m6") { state.sensorsLost = t.checked; stopScenario(); render(); }
    else if (t.id === "scenario-select") { stopScenario(); state.scenario = t.value || null; state.scenarioT = 0; drawScenarioBar(); }
    else if (t.dataset.step) { const w = myJobs()[0]; doStep("technician", w.work_order_id, Number(t.dataset.step), state.techId); render(); }
    else if (t.dataset.sym !== undefined) { const w = myJobs()[0]; const set = (state.inspection[w.work_order_id] ||= new Set()); t.checked ? set.add(t.dataset.sym) : set.delete(t.dataset.sym); render(); }
  });
  $("#as-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("#as-input").value.trim();
    if (!v) return;
    $("#as-input").value = "";
    ask(v, state.persona); render();
  });

  setInterval(() => syncTick(), 1500);
  scenarioUI();
  (async () => {
    try { const r = await fetch("/api/health"); state.api = r.ok && (await r.json()).ok === true; } catch { state.api = false; }
    render();
  })();
  selectWO(state.selectedWO);
})();
