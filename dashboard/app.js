/* hybrid-ai Field Ops demo dashboard.
 * Data: data.js (window.HYBRID_DATA) from `python -m hybrid_ai.demo.build_data`.
 * Repair plans: /api/recommendations (SQLite) when served by `python -m hybrid_ai.demo.server`;
 * falls back to the embedded data when the API isn't there.
 * Three modes (Online / Limited / Offline), two events (cloud AI outage, sensors lost),
 * three places (Cloud, Edge, Device). See docs/DESIGN.md §2 and §5.
 */
(() => {
  "use strict";
  const D = window.HYBRID_DATA;
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ------------------------------------------------------------------ modes, places, models
  const MODES = {
    ONLINE: { name: "Online", color: "var(--online)", dark: false, desc: "Cloud reachable at normal speed", cloud: "up", tel: 30 },
    LIMITED: { name: "Limited", color: "var(--limited)", dark: true, desc: "Slow or intermittent link: device and edge answer first, cloud in windows", cloud: "flaky", tel: 900 },
    OFFLINE: { name: "Offline", color: "var(--offline)", dark: false, desc: "No WAN: only the device and the site edge", cloud: "down", tel: null },
  };
  const PLACE = { cloud: "Cloud", edge: "Edge", device: "Device", none: "Unavailable" };
  const PRIO_LABEL = { P0: "Safety", P1: "Control", P2: "Context", P3: "Knowledge", P4: "Bulk" };
  const PERSONA_NAME = { supervisor: "Supervisor", technician: "Technician", walkthrough: "Assigned tech" };
  const MODELS = {
    "claude-opus-5-5": { prefill: 4000, decode: 70 },
    "claude-haiku-5-5": { prefill: 9000, decode: 170 },
    "edge-local-14b": { prefill: 1500, decode: 40 },
    "device-local-3b": { prefill: 600, decode: 25 },
  };
  const NET = { ONLINE: { rtt: 90, kbps: 10000 }, LIMITED: { rtt: 700, kbps: 256 }, OFFLINE: { rtt: 0, kbps: 1 } };
  const RM = window.HYBRID_DATA.repair_model;   // trained repair recommendation model (same weights in every place)

  // JavaScript port of hybrid_ai.models.repair_model.predict: runs in the browser exactly as on device/edge/cloud.
  function rmPredict(assetModel, readings, trends, symptoms) {
    const tm = RM.types[assetModel], th = window.HYBRID_DATA.telemetry, sym = new Set(symptoms || []);
    const base = {};
    for (const a of window.HYBRID_DATA.assets) if (a.model === assetModel) { Object.entries(th[a.asset_id].thresholds).forEach(([k, v]) => (base[k] = v.baseline)); break; }
    const x = tm.features.map((f) => {
      const [kind, name] = [f.slice(0, f.indexOf(":")), f.slice(f.indexOf(":") + 1)];
      if (f === "has_telemetry") return readings ? 1 : 0;
      if (kind === "dev") return readings && name in readings ? (readings[name] - base[name]) / base[name] : 0;
      if (kind === "trend") return trends && name in trends ? trends[name] : 0;
      return sym.has(name) ? 1 : 0;
    });
    const xs = x.map((v, j) => (v - tm.mean[j]) / tm.std[j]);
    const z = tm.weights.map((w, k) => tm.bias[k] + tm.log_prior[k] + w.reduce((acc, wj, j) => acc + wj * xs[j], 0));
    const m = Math.max(...z), e = z.map((v) => Math.exp(v - m)), t = e.reduce((a, b) => a + b, 0);
    return tm.classes.map((c, k) => ({ cause_code: c, probability: e[k] / t })).sort((a, b) => b.probability - a.probability);
  }

  // ------------------------------------------------------------------ state
  const byId = (arr, key) => Object.fromEntries(arr.map((x) => [x[key], x]));
  const ASSETS = byId(D.assets, "asset_id");
  const TECHS = byId(D.technicians, "technician_id");
  const DEPOTS = byId(D.depots, "depot_id");
  const WOS = byId(D.work_orders, "work_order_id");
  const NOW0 = new Date(D.generated.now).getTime();
  const WT_WO = D.work_orders.find((w) => w.assigned_technician_id);

  const state = {
    persona: "supervisor", view: "topo", mode: "ONLINE", aiDown: false, sensorsLost: false, simOffset: 0, offlineSince: null,
    selectedWO: D.work_orders[0]?.work_order_id,
    techId: WT_WO?.assigned_technician_id || D.technicians[0].technician_id,
    techTab: "plan", techPos: null,
    queue: [], feed: {}, techView: {},
    van: Object.fromEntries(D.technicians.map((t) => [t.technician_id, Object.fromEntries(t.van_stock.map((p) => [p.part_number, p.qty]))])),
    inspection: {}, plans: {}, stepLocal: {},
    scenario: null, scenarioT: 0, playing: false, timer: null,
    log: [], chat: [], liveOpen: true, assistantOpen: false, api: false,
    agentAt: {},     // agent -> place it last ran in
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
  const pct = (p) => (p >= 0.995 ? ">99%" : `${Math.round(p * 100)}%`);
  const mode = () => MODES[state.mode];
  const offlineAge = () => (state.offlineSince == null ? null : Math.max(0, state.simOffset - state.offlineSince) + 1800);
  const isField = (who) => who !== "supervisor";
  const firstName = (id) => TECHS[id].name.split(" ")[0];
  const modeLabel = () => `${mode().name}${state.aiDown ? " + cloud AI outage" : ""}${state.sensorsLost ? " + sensors lost" : ""}`;

  // Can this requester reach the cloud right now? The supervisor works from the office (always online);
  // the mode describes the technician's link. In Limited, the link is up only in windows.
  function cloudReach(who) {
    if (!isField(who)) return true;
    const c = mode().cloud;
    return c === "up" || (c === "flaky" && Math.random() < 0.45);
  }
  const edgeAlive = () => !state.sensorsLost;   // sensors lost = gateway dark (e.g. site power cut)

  function costMs(p) {
    let ms = 0;
    if (p.tier === "cloud") {
      const n = isField(p.who) ? NET[state.mode] : NET.ONLINE;
      ms += n.rtt + ((p.kb || 2) * 8 / n.kbps) * 1000;
    } else if (p.tier === "edge") ms += isField(p.who) ? 15 : NET[state.mode].rtt || 90;
    else ms += 5;
    if (p.model && MODELS[p.model]) ms += (p.tin / MODELS[p.model].prefill + p.tout / MODELS[p.model].decode) * 1000;
    else if (p.model === RM.version) ms += 2 + Math.random() * 4;   // tiny model: a few ms anywhere
    else ms += 20 + Math.random() * 40;
    return Math.round(ms * (0.85 + Math.random() * 0.3));
  }

  // ------------------------------------------------------------------ router: where each request runs, and why
  function route(tool, who) {
    const field = isField(who), cloud = cloudReach(who), M = field ? modeLabel() : "Office (online)";
    const P = (tier, why, extra = {}) => ({ tier, why, model: null, tin: 0, tout: 0, kb: 2, status: "ok", ...extra });
    switch (tool) {
      case "diagnose_issue":   // the repair recommendation model: same weights in every place, no tokens
        if (state.sensorsLost && field) return P("device", `${M}: edge is dark, so the device copy of the model ranks causes from observed symptoms`, { model: RM.version });
        if (!field || (cloud && state.mode === "ONLINE")) return P("cloud", `${M}: cloud copy with full fleet features${state.aiDown ? "; it's not an LLM, so the AI outage doesn't matter" : ""}`, { model: RM.version, kb: 6 });
        return P("edge", `${M}: edge copy runs next to the compressor's telemetry, no WAN needed`, { model: RM.version });
      case "find_technicians":
        if (cloud) return P("cloud", state.aiDown ? `${M}: dispatch optimizer is deterministic, so the AI outage doesn't matter` : field && state.mode === "LIMITED" ? `${M}: cloud answered within the 3 s deadline` : `${M}: live roster, GPS and SLA`, { kb: 6 });
        if (state.mode === "LIMITED") return P("edge", `${M}: cloud missed the 3 s deadline, so the depot roster snapshot (provisional)`);
        return P("none", `${M}: dispatch isn't available offline; call the dispatcher`, { status: "failed" });
      case "recommend_repair_location":
        if (cloud && !(field && state.mode === "LIMITED")) return P("cloud", `${M}: learned + rule score`);
        return P(field ? "device" : "cloud", `${M}: rule score computed locally`);
      case "check_parts":
        if (cloud) return P("cloud", `${M}: live ERP stock (van, depot, warehouse, vendor)`);
        if (state.mode === "LIMITED") return P("edge", `${M}: depot mirror at the edge (soft data)`);
        return P("device", `${M}: no uplink, so van stock only`);
      case "reserve_parts":
        if (cloud) return P("cloud", `${M}: hard reservation in the ERP`);
        return P("device", `${M}: soft reservation queued in the outbox`, { status: "queued" });
      case "search_knowledge":
        if (field) return P("device", "The mission pack already has this compressor's manuals and history: no network needed");
        return P("cloud", "Full knowledge base in the cloud");
      case "get_live_telemetry":
        if (state.sensorsLost) return P("none", `${M}: site gateway not reporting`, { status: "failed" });
        if (field) return P("edge", "Local Wi-Fi/BLE link to the site gateway, no WAN needed");
        return state.mode === "OFFLINE" ? P("cloud", "Site offline: last known copy in the cloud", { status: "stale" })
          : P("cloud", `${mode().name}: edge streams features to the cloud`);
      case "repair_db.get_plan":
        if (cloud) return P("cloud", `${M}: live plan from the repair recommendations DB`, { kb: 12 });
        return P("device", `${M}: copy of the plan from the mission pack DB`);
      case "repair_db.update_step": case "repair_db.outcome": case "update_work_order":
        if (cloud) return P("cloud", `${M}: written to the cloud database`);
        return P("device", `${M}: queued in the device outbox`, { status: "queued" });
      case "sync_mission_pack":
        if (cloud && state.mode === "ONLINE") return P("cloud", "Online at the depot: P3 knowledge download", { kb: 4200 });
        return P("none", `${M}: pack downloads wait for a good link (P3)`, { status: "failed" });
      case "compose_answer":
        if (cloud && !state.aiDown && !(field && state.mode === "OFFLINE")) return P("cloud", `${M}: small fast cloud model writes the answer`, { model: "claude-haiku-5-5", tin: 900, tout: 140, kb: 4 });
        if (edgeAlive() && field) return P("edge", `${M}: edge model writes the answer`, { model: "edge-local-14b", tin: 900, tout: 120 });
        if (!field) return P("cloud", `${M}: cloud AI down, so a templated answer`);
        return P("device", `${M}: device model writes the answer`, { model: "device-local-3b", tin: 700, tout: 100 });
      case "local_status":
        return P("device", "Answered from the device's own state, no model needed");
      default:
        return P("device", "local");
    }
  }

  // Which agent / database a tool belongs to (for the topology view)
  const TOOL_AGENT = { diagnose_issue: "repairrec", find_technicians: "dispatch", recommend_repair_location: "logistics", check_parts: "logistics", reserve_parts: "logistics", compose_answer: "assistant" };
  function toolDb(tool, tier) {
    const m = {
      cloud: { "repair_db.get_plan": "repairdb", "repair_db.update_step": "repairdb", "repair_db.outcome": "repairdb", update_work_order: "cmms", search_knowledge: "kb", get_live_telemetry: "fleettel", check_parts: "cmms", reserve_parts: "cmms", find_technicians: "cmms", diagnose_issue: "registry", sync_mission_pack: "repairdb" },
      edge: { get_live_telemetry: "telbuf", diagnose_issue: "edgemodel", check_parts: "mirror", find_technicians: "mirror", compose_answer: "telbuf" },
      device: { "repair_db.get_plan": "pack", search_knowledge: "pack", "repair_db.update_step": "outbox", "repair_db.outcome": "outbox", update_work_order: "outbox", reserve_parts: "outbox", check_parts: "van", diagnose_issue: "devmodel", local_status: "outbox" },
    };
    return m[tier]?.[tool];
  }

  function callTool(tool, who, request, extra = {}) {
    const p = { ...route(tool, who), who, ...extra };
    p.ms = p.status === "failed" ? (isField(who) ? 3000 : 400) : costMs(p);
    const entry = { id: ++logSeq, t: state.simOffset, who, via: extra.via, request, tool, tier: p.tier, model: p.model, why: p.why, ms: p.ms, tin: p.tin, tout: p.tout, status: p.status };
    state.log.push(entry);
    if (state.log.length > 400) state.log.shift();
    if (TOOL_AGENT[tool] && p.tier !== "none") state.agentAt[TOOL_AGENT[tool]] = p.tier;
    renderLive(entry.id);
    topoActivity(tool, who, p);
    return p;
  }

  // ------------------------------------------------------------------ provenance chips
  function provFor(tool, who) {
    const p = route(tool, who);
    const conf = p.status === "failed" ? "unavailable" : p.tier === "cloud" ? (p.status === "stale" ? "stale" : "confirmed") : "provisional";
    let age = 0;
    if (p.tier === "edge") age = tool === "find_technicians" || tool === "check_parts" ? 3 * 3600 : 5;
    if (p.tier === "device") age = offlineAge() ?? 600;
    const ageTxt = p.tier === "none" ? "" : ` · ${fmtAge(age)}`;
    return { ...p, conf, html: `<span class="prov ${p.tier}" title="${esc(p.why)}">${PLACE[p.tier]} <span class="conf">· ${conf}${ageTxt}</span></span>` };
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
      .concat((D.history[a.asset_id] || []).slice(0, 3).map((r) => ({ kind: "asset_repair", ref_id: r.date, title: `${r.date} · ${r.cause_code} on this compressor`, detail: r.notes })));
    return {
      work_order_id: w.work_order_id, asset_id: a.asset_id, model: a.model, category: a.category, site_name: a.site_name,
      priority: w.priority, status: w.status, cause_code: top.cause_code, cause_description: top.description,
      severity: w.diagnosis.severity, safe_to_run: w.diagnosis.safe_to_run, safety_override: w.diagnosis.safety_override,
      repair_location: w.location.location, est_hours: w.est_hours, version: 1, generated_by: `${RM.version} model + planning rules`,
      model_version: RM.version, model_confidence: w.diagnosis.model_confidence,
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
  const allowed = (prio) => state.mode === "ONLINE" || (state.mode === "LIMITED" && ["P0", "P1", "P2"].includes(prio));
  function syncTick(immediate = false, forceWindow = false) {
    let changed = false;
    const order = { P0: 0, P1: 1, P2: 2, P3: 3, P4: 4 };
    const pending = state.queue.filter((q) => q.status !== "synced").sort((a, b) => order[a.prio] - order[b.prio] || a.id - b.id);
    for (const q of pending) {
      if (!allowed(q.prio)) continue;
      const up = forceWindow || mode().cloud === "up" || (mode().cloud === "flaky" && Math.random() < 0.45);
      if (!up || (immediate && state.mode === "LIMITED" && !forceWindow)) continue;
      q.status = "synced"; changed = true;
      apply(q);
    }
    if (changed) render();
  }
  function apply(q) {
    const age = ((state.simOffset - q.created) / 3600).toFixed(1);
    if (q.dir === "up") {
      (state.feed[q.wo] ||= []).push({ t: state.simOffset, text: q.text });
      if (q.created !== state.simOffset) {
        const tool = q.kind === "step" ? "repair_db.update_step" : q.kind === "complete" ? "repair_db.outcome" : q.kind === "photo" ? "upload_media" : "update_work_order";
        const ms = Math.round((q.kind === "photo" ? 3200 * 8 / NET[state.mode].kbps * 1000 : NET[state.mode].rtt + 40) * (0.85 + Math.random() * 0.3));
        const entry = { id: ++logSeq, t: state.simOffset, who: "outbox", request: `Replay: ${q.text}`, tool, tier: "cloud", model: null,
          why: `Link back: ${q.prio} replayed after ${age} h; the idempotency key keeps it single`, ms, tin: 0, tout: 0, status: "ok" };
        state.log.push(entry); renderLive(entry.id); topoPacket("device", "cloud", "sync");
      }
      if (q.kind === "step") {
        api(`/api/recommendations/${q.wo}/steps/${q.payload.seq}`, { status: "done", by: q.payload.by, idempotency_key: q.key, origin_tier: q.created === state.simOffset ? "cloud" : "device" });
        if (state.stepLocal[q.wo]) state.stepLocal[q.wo][q.payload.seq] = "synced";
      }
      if (q.kind === "complete") {
        WOS[q.wo].status = "completed"; ASSETS[WOS[q.wo].asset_id].status = "healthy";
        api(`/api/recommendations/${q.wo}/outcome`, { confirmed_cause: q.payload.cause, by: q.payload.by, notes: q.payload.notes || "" });
      }
    } else if (q.kind === "assign") {
      state.techView[q.wo] = { status: "assigned", assigned: q.payload.tech };
    }
  }

  // ------------------------------------------------------------------ topology: where agents and databases run
  const AGENTS = [
    { id: "orchestrator", name: "Orchestrator" }, { id: "repairrec", name: "Repair-rec model", kind: "ml" }, { id: "dispatch", name: "Dispatch" },
    { id: "logistics", name: "Logistics" }, { id: "assistant", name: "Assistant model" }, { id: "safety", name: "Safety rules" },
    { id: "field", name: "Field assistant" }, { id: "sync", name: "Sync service" },
  ];
  // Where each agent runs by default in the current mode (requests then move them).
  function defaultPlace(id) {
    const on = state.mode === "ONLINE", lim = state.mode === "LIMITED";
    switch (id) {
      case "orchestrator": return state.mode === "OFFLINE" ? "device" : "cloud";
      case "repairrec": return state.sensorsLost ? "device" : on ? "cloud" : "edge";
      case "dispatch": return on ? "cloud" : lim ? "edge" : "cloud";
      case "logistics": return on ? "cloud" : lim ? "edge" : "device";
      case "assistant": return on && !state.aiDown ? "cloud" : state.sensorsLost ? "device" : "edge";
      case "safety": return "edge";
      default: return "device";
    }
  }
  function agentState(id) {
    if (id === "dispatch" && state.mode === "OFFLINE") return "unreachable";
    if (id === "safety" && state.sensorsLost) return "dark";
    if (id === "orchestrator" && state.mode === "OFFLINE") return "reduced";
    return "";
  }
  function dbList() {
    const plan = state.plans[(currentJob() || WOS[state.selectedWO])?.work_order_id];
    const queued = state.queue.filter((q) => q.dir === "up" && q.status !== "synced").length;
    const vanN = Object.values(state.van[state.techId]).reduce((a, b) => a + b, 0);
    const telOK = !state.sensorsLost;
    const ver = Object.values(state.plans).reduce((m, p) => Math.max(m, p.plan.version || 1), 1);
    return {
      cloud: [["registry", "Model registry", `${RM.version} · top-1 ${Math.round(RM.metrics.top1 * 100)}% on held-out data`],
              ["repairdb", "Repair recommendations DB", `${D.work_orders.length} plans · ${state.api ? "SQLite, live" : "embedded"} · v${ver}`],
              ["cmms", "Work orders + ERP", "orders, stock, roster"],
              ["kb", "Knowledge base", "manuals, repair history"],
              ["fleettel", "Fleet telemetry", telOK && state.mode !== "OFFLINE" ? `fed by edge · ${fmtAge(mode().tel)}` : "not updating"]],
      edge: [["edgemodel", "Repair-rec model copy", telOK ? `${RM.version} · runs on live telemetry` : "dark (no power)"],
             ["telbuf", "Telemetry buffer", telOK ? "live · 7–30 days" : "dark (no power)"],
             ["rules", "Safety rules", telOK ? "active" : "dark"],
             ["mirror", "Depot mirror", "stock, roster, regional KB · 3 h old"]],
      device: [["pack", "Mission pack DB", plan ? `plan v${plan.plan.version} · ${plan.source === "db" ? "synced" : "local copy"}` : "manuals, history"],
               ["devmodel", "Repair-rec model copy", `${RM.version} · 9 KB · symptoms or readings`],
               ["outbox", "Outbox", queued ? `${queued} queued` : "empty"],
               ["van", "Van stock", `${vanN} parts`]],
    };
  }
  function linkState() {
    const c = mode().cloud;
    return {
      "device-cloud": c === "up" ? "up" : c === "flaky" ? "flaky" : "down",
      "edge-cloud": state.sensorsLost ? "down" : c === "up" ? "up" : c === "flaky" ? "flaky" : "down",
      "device-edge": state.sensorsLost ? "down" : "up",
    };
  }
  function placeStatus(p) {
    if (p === "cloud") return state.mode === "OFFLINE" ? ["unreachable from the field", "down"] : state.aiDown ? ["data up · AI outage", "warn"] : state.mode === "LIMITED" ? ["reachable in windows", "warn"] : ["reachable", "up"];
    if (p === "edge") return state.sensorsLost ? ["dark: no power or sensors", "down"] : ["running next to the compressor", "up"];
    return ["always available", "up"];
  }

  let topoBuilt = false;
  function buildTopo() {
    const el = $("#topo");
    const zone = (p, sub) => `<div class="zone" data-place="${p}"><div class="zone-h"><span class="zone-ic ${p}"></span><div><b>${PLACE[p]}</b><div class="zone-sub">${sub}</div></div><span class="zone-st"></span></div>
      <div class="zone-agents" data-agents="${p}"></div><div class="zone-dbs" data-dbs="${p}"></div></div>`;
    el.innerHTML = `<svg class="topo-links" aria-hidden="true"></svg>
      <div class="zones">${zone("device", "technician tablet")}${zone("edge", "site gateway + depot server")}${zone("cloud", "authoritative")}</div>
      ${AGENTS.map((a) => `<div class="agent" data-agent="${a.id}"><span class="ag-dot"></span><span class="ag-name">${esc(a.name)}</span><span class="ag-model"></span></div>`).join("")}`;
    topoBuilt = true;
    new ResizeObserver(() => layoutTopo()).observe(el);
  }
  function renderTopo() {
    if (!topoBuilt) buildTopo();
    const dbs = dbList();
    for (const p of ["device", "edge", "cloud"]) {
      const z = $(`.zone[data-place="${p}"]`), [txt, cls] = placeStatus(p), st = z.querySelector(".zone-st");
      st.className = `zone-st ${cls}`; st.textContent = txt;
      z.classList.toggle("dim", cls === "down");
      z.querySelector(".zone-dbs").innerHTML = dbs[p].map(([id, name, s]) => `<div class="db" data-db="${id}"><span class="db-ic"></span><span><b>${esc(name)}</b><span class="db-st">${esc(s)}</span></span></div>`).join("");
    }
    layoutTopo();
  }
  const MODEL_AT = { cloud: "claude", edge: "edge 14B", device: "device 3B" };
  function layoutTopo() {
    const el = $("#topo");
    if (!topoBuilt || el.offsetParent === null) return;
    const box = el.getBoundingClientRect(), counts = { device: 0, edge: 0, cloud: 0 }, CH = 26, GAP = 4;
    const areaW = el.querySelector('[data-agents="device"]').getBoundingClientRect().width;
    const perRow = areaW > 250 ? 2 : 1, cw = (areaW - GAP * (perRow - 1)) / perRow;
    const place = Object.fromEntries(AGENTS.map((a) => [a.id, state.agentAt[a.id] || defaultPlace(a.id)]));
    for (const p of ["device", "edge", "cloud"]) {
      const n = AGENTS.filter((a) => place[a.id] === p).length;
      el.querySelector(`[data-agents="${p}"]`).style.height = `${Math.max(1, Math.ceil(n / perRow)) * (CH + GAP)}px`;
    }
    for (const a of AGENTS) {
      const p = place[a.id], area = el.querySelector(`[data-agents="${p}"]`).getBoundingClientRect(), chip = el.querySelector(`[data-agent="${a.id}"]`);
      const i = counts[p]++;
      chip.style.width = `${cw}px`;
      chip.style.transform = `translate(${area.left - box.left + (i % perRow) * (cw + GAP)}px, ${area.top - box.top + Math.floor(i / perRow) * (CH + GAP)}px)`;
      const st = agentState(a.id);
      chip.className = `agent at-${p} ${st} ${a.kind === "ml" ? "ml" : ""}`;
      chip.title = `${a.name}: running on ${PLACE[p]}${st ? ` (${st})` : ""}`;
      chip.querySelector(".ag-model").textContent = a.id === "assistant" && !st ? MODEL_AT[p] : a.id === "repairrec" ? "0 tokens" : st;
    }
    drawLinks();
    if (!el.classList.contains("ready")) requestAnimationFrame(() => el.classList.add("ready"));  // animate moves, not the first placement
  }
  function zoneHead(p) {
    const el = $("#topo"), box = el.getBoundingClientRect(), r = el.querySelector(`.zone[data-place="${p}"] .zone-h`).getBoundingClientRect();
    return { cx: r.left - box.left + r.width / 2, cy: r.top - box.top + r.height / 2, l: r.left - box.left, r: r.right - box.left, top: r.top - box.top };
  }
  function linkPath(a, b) {
    if ((a === "device" && b === "cloud") || (a === "cloud" && b === "device")) {
      const s = zoneHead(a), e = zoneHead(b), up = Math.min(s.top, e.top) - 4;
      return `M ${s.cx} ${s.top} C ${s.cx} ${up - 22}, ${e.cx} ${up - 22}, ${e.cx} ${e.top}`;
    }
    const A = zoneHead(a), B = zoneHead(b), left = A.cx < B.cx;
    return `M ${left ? A.r : A.l} ${A.cy} L ${left ? B.l : B.r} ${B.cy}`;
  }
  function drawLinks() {
    const svg = $(".topo-links"), ls = linkState(), lab = { flaky: "in windows", down: "down" };
    let html = "", labels = "";
    for (const [k, st] of Object.entries(ls)) {
      const [a, b] = k.split("-"), d = linkPath(a, b);
      html += `<path class="lk ${st}" d="${d}"/>`;
      if (lab[st]) {
        const tmp = document.createElementNS("http://www.w3.org/2000/svg", "path");
        tmp.setAttribute("d", d); svg.appendChild(tmp);
        const pt = tmp.getPointAtLength(tmp.getTotalLength() / 2); tmp.remove();
        labels += `<text class="lk-t ${st}" x="${pt.x}" y="${pt.y - 5}" text-anchor="middle">${lab[st]}</text>`;
      }
    }
    svg.innerHTML = html + labels;
  }
  function topoPacket(from, to, kind = "req", back = false) {
    if (!topoBuilt || $("#topo").offsetParent === null || from === to) return;
    const svg = $(".topo-links"), NS = "http://www.w3.org/2000/svg";
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("r", "5"); c.setAttribute("class", `pkt ${kind}`);
    const m = document.createElementNS(NS, "animateMotion");
    m.setAttribute("path", linkPath(from, to)); m.setAttribute("fill", "freeze");
    m.setAttribute("dur", back ? "1.2s" : "0.7s");
    if (back) { m.setAttribute("keyPoints", "0;1;0"); m.setAttribute("keyTimes", "0;0.5;1"); m.setAttribute("calcMode", "linear"); }
    c.appendChild(m); svg.appendChild(c);
    try { m.beginElement(); } catch { /* older engines start it automatically */ }
    setTimeout(() => c.remove(), back ? 1300 : 800);
  }
  function flash(sel) {
    const el = $(sel);
    if (!el) return;
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  }
  function topoActivity(tool, who, p) {
    if (!topoBuilt || $("#topo").offsetParent === null) return;
    const origin = isField(who) ? "device" : "cloud";
    if (p.tier === "none") { flash(`.zone[data-place="${tool === "get_live_telemetry" ? "edge" : "cloud"}"] .zone-h`); return; }
    layoutTopo();
    if (TOOL_AGENT[tool]) flash(`[data-agent="${TOOL_AGENT[tool]}"]`);
    const db = toolDb(tool, p.tier);
    if (db) flash(`[data-db="${db}"]`);
    flash(`.zone[data-place="${p.tier}"] .zone-h`);
    if (p.tier !== origin) topoPacket(origin, p.tier, p.status === "queued" ? "queued" : "req", true);
    if (tool === "get_live_telemetry" && !isField(who)) topoPacket("edge", "cloud", "data");
    if (tool === "sync_mission_pack") { topoPacket("cloud", "device", "data"); flash('[data-db="pack"]'); }
  }

  // ------------------------------------------------------------------ map
  const map = L.map("map", { zoomControl: true }).setView([36.8, -119.4], 6);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
  const STATUS_COLOR = { healthy: "#2e8b57", warning: "#e0a100", fault: "#b83227" };
  const layers = { asset: L.layerGroup().addTo(map), depot: L.layerGroup().addTo(map), tech: L.layerGroup().addTo(map), route: L.layerGroup().addTo(map) };
  function assetPopup(a) {
    const wo = a.work_order_id ? `<br><a href="#" data-open-wo="${a.work_order_id}">${a.work_order_id}</a>` : "";
    return `<b>${esc(a.asset_id)}</b> · ${esc(a.model)}<br>${esc(a.category)}<br>${esc(a.site_name)} (${esc(a.region)})<br>Coverage: <b>${esc(a.coverage)}</b> · Status: <b style="color:${STATUS_COLOR[a.status]}">${a.status}</b>${wo}`;
  }
  const techLatLon = () => (state.techPos && state.persona === "walkthrough" ? state.techPos : [TECHS[state.techId].lat, TECHS[state.techId].lon]);
  function drawMap() {
    Object.values(layers).forEach((l) => l.clearLayers());
    const field = isField(state.persona), job = field ? currentJob() : null;
    for (const d of D.depots) {
      L.marker([d.lat, d.lon], { icon: L.divIcon({ className: "", html: `<div class="depot-icon" style="width:26px;height:20px">${d.has_workshop ? "WS" : "DEP"}</div>`, iconSize: [26, 20] }), title: `${d.city} depot` })
        .bindPopup(`<b>${esc(d.city)} depot</b> (${esc(d.depot_id)})<br>Edge server${d.has_workshop ? " + workshop" : ""}`).addTo(layers.depot);
    }
    for (const a of D.assets) {
      const hl = (!field && a.work_order_id === state.selectedWO) || (job && job.asset_id === a.asset_id);
      L.circleMarker([a.lat, a.lon], { radius: hl ? 11 : a.status === "healthy" ? 6 : 8, color: hl ? "#14232b" : "#ffffff", weight: hl ? 3 : 2, fillColor: STATUS_COLOR[a.status], fillOpacity: 0.95 }).bindPopup(assetPopup(a)).addTo(layers.asset);
    }
    const techs = field ? [TECHS[state.techId]] : D.technicians.filter((t) => t.on_shift);
    for (const t of techs) {
      const ini = t.name.split(" ").map((p) => p[0]).join("");
      L.marker(field ? techLatLon() : [t.lat, t.lon], { icon: L.divIcon({ className: "", html: `<div class="tech-icon ${field ? "me" : ""}" style="width:24px;height:24px">${esc(ini)}</div>`, iconSize: [24, 24] }), title: t.name, zIndexOffset: 500 })
        .bindPopup(`<b>${esc(t.name)}</b> (${esc(t.technician_id)})<br>Van ${esc(t.van_id)} · ${esc(t.skills.join(", "))}`).addTo(layers.tech);
    }
    if (job) { const a = ASSETS[job.asset_id], t = TECHS[state.techId]; L.polyline([[t.lat, t.lon], [a.lat, a.lon]], { color: "#14232b", weight: 3, dashArray: "6 6", opacity: 0.6 }).addTo(layers.route); }
  }
  map.on("popupopen", (e) => {
    const link = e.popup.getElement().querySelector("[data-open-wo]");
    if (link) link.addEventListener("click", (ev) => { ev.preventDefault(); setPersona("supervisor"); selectWO(link.dataset.openWo); });
  });
  function focusMap() {
    if (state.view !== "map") return;
    if (isField(state.persona)) {
      const job = currentJob(), t = TECHS[state.techId], pts = [[t.lat, t.lon]];
      if (job) pts.push([ASSETS[job.asset_id].lat, ASSETS[job.asset_id].lon]);
      map.fitBounds(L.latLngBounds(pts).pad(0.6), { maxZoom: 10 });
    } else if (state.selectedWO) {
      const a = ASSETS[WOS[state.selectedWO].asset_id];
      map.setView([a.lat, a.lon], Math.max(map.getZoom(), 7), { animate: true });
    }
  }
  function setView(v) {
    state.view = v;
    document.querySelectorAll(".view-tab").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
    $("#topo").hidden = v !== "topo";
    $(".map-box").hidden = v !== "map";
    if (v === "map") setTimeout(() => { map.invalidateSize(); drawMap(); focusMap(); }, 30);
    else renderTopo();
  }

  // ------------------------------------------------------------------ shared widgets
  function spark(sig, series, th, stale) {
    const pts = series.points.map((p) => p.value), W = 400, H = 56, pad = 4;
    const lines = [th.warn, th.trip].filter((v) => v != null);
    const lo = Math.min(...pts, ...lines), hi = Math.max(...pts, ...lines);
    const y = (v) => H - pad - ((v - lo) / (hi - lo || 1)) * (H - 2 * pad);
    const x = (i) => pad + (i / (pts.length - 1)) * (W - 2 * pad);
    const path = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const guide = (v, c) => (v == null ? "" : `<line x1="0" x2="${W}" y1="${y(v)}" y2="${y(v)}" stroke="${c}" stroke-dasharray="4 4" stroke-width="1.5"/>`);
    const last = pts[pts.length - 1];
    const breach = th.warn != null && (th.low_is_bad ? last <= th.warn : last >= th.warn);
    return `<div class="sig"><div class="row"><b>${esc(sig)}</b><span class="${breach ? "bad" : "muted"}">${last.toFixed(1)} ${esc(series.unit)}${th.warn != null ? ` · warn ${th.low_is_bad ? "<" : ">"} ${th.warn}` : ""}</span></div>
      <svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(sig)} trend">${guide(th.warn, "#e0a100")}${guide(th.trip, "#b83227")}<path d="${path}" fill="none" stroke="${stale ? "#93a7b0" : "#1b8a8f"}" stroke-width="2"/></svg></div>`;
  }
  function telemetryBlock(assetId, ageS, lostMsg) {
    const T = D.telemetry[assetId];
    if (ageS === null) return `<div class="note">${lostMsg}</div>`;
    const stale = ageS > 600;
    const al = T.alarms.slice(-3).map((a) => `<div><span class="pill ${a.severity === "critical" ? "pri-urgent" : "pri-soon"}">${esc(a.code)}</span> <span class="muted">${esc(a.ts.slice(11, 16))}</span></div>`).join("");
    return `${stale ? `<div class="note">Last known values, ${fmtAge(ageS)}. The site isn't sending right now.</div>` : ""}${T.series.map((s) => spark(s.signal, s, T.thresholds[s.signal], stale)).join("")}${al ? `<div class="sub" style="margin-top:4px">Recent alarms</div>${al}` : ""}`;
  }
  const causesBlock = (causes) => causes.map((c) => `<div class="cause"><span>${esc(c.description)} <span class="muted">${esc(c.cause_code)}</span></span><div class="bar"><span style="width:${Math.round(c.probability * 100)}%"></span></div><b>${pct(c.probability)}</b></div>`).join("");

  // ------------------------------------------------------------------ KPIs
  function kpis() {
    const open = D.work_orders.filter((w) => w.status !== "completed");
    const pending = D.work_orders.reduce((n, w) => n + w.approvals.filter((a) => a.outcome === "human").length, 0);
    const faults = D.assets.filter((a) => a.status !== "healthy").length;
    const queued = state.queue.filter((q) => q.dir === "up" && q.status !== "synced").length;
    const tiles = state.persona === "supervisor"
      ? [[D.assets.length, "Compressors"], [faults, "Need attention", faults > 0], [open.length, "Open work orders"], [pending, "Approvals waiting", pending > 0], [queued, "Field updates in transit", queued > 0]]
      : [[myJobs().length || (state.persona === "walkthrough" ? 1 : 0), "My jobs"], [Object.values(state.van[state.techId]).reduce((a, b) => a + b, 0), "Parts in van"], [queued, "Outbox (not synced)", queued > 0], [mode().name, "Network mode"], [state.sensorsLost ? "Lost" : "OK", "Equipment data", state.sensorsLost]];
    $("#kpis").innerHTML = tiles.map(([v, l, alert]) => `<div class="kpi ${alert ? "alert" : ""}"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
  }

  // ------------------------------------------------------------------ supervisor
  function selectWO(id) {
    state.selectedWO = id;
    const w = WOS[id];
    for (const tool of ["diagnose_issue", "find_technicians", "recommend_repair_location", "check_parts"]) callTool(tool, "supervisor", `Review ${id}: ${tool.replaceAll("_", " ")}`);
    callTool("get_live_telemetry", "supervisor", `Review ${id}: telemetry for ${w.asset_id}`);
    render(); focusMap();
  }
  function supervisorPanel() {
    const list = D.work_orders.map((w) => {
      const a = ASSETS[w.asset_id], waiting = w.approvals.filter((x) => x.outcome === "human").length;
      return `<div class="card click ${w.work_order_id === state.selectedWO ? "selected" : ""}" data-wo="${w.work_order_id}">
        <div class="row"><b>${esc(w.work_order_id)}</b><span><span class="pill pri-${w.priority}">${esc(w.priority)}</span> <span class="pill st st-${w.status}">${esc(w.status.replace("_", " "))}</span></span></div>
        <div>${esc(w.title)}</div><div class="sub">${esc(a.asset_id)} · ${esc(a.region)} · ${w.source === "telemetry" ? "detected from telemetry" : "reported"}${waiting ? ` · <b>${waiting} approval${waiting > 1 ? "s" : ""} waiting</b>` : ""}</div></div>`;
    }).join("");
    const w = WOS[state.selectedWO];
    return `<h2>Dispatch board</h2><div class="sub">Agents propose; rules or the supervisor approve. Every answer shows where it ran and how fresh it is.</div><h3>Work orders</h3>${list}${w ? woDetail(w) : ""}`;
  }
  function woDetail(w) {
    const a = ASSETS[w.asset_id], d = w.diagnosis;
    const p1 = provFor("diagnose_issue", "supervisor"), p2 = provFor("find_technicians", "supervisor"), p3 = provFor("recommend_repair_location", "supervisor"), p4 = provFor("check_parts", "supervisor");
    const techs = w.technicians.slice(0, 3).map((c) => `<tr><td><b>${esc(c.name)}</b><div class="muted">${esc(c.technician_id)}</div></td><td>${Math.round(c.score * 100)}</td><td>${c.distance_km} km<div class="muted">${c.eta_min} min</div></td><td>${c.available ? '<span class="ok">on shift</span>' : '<span class="muted">off</span>'}${c.missing_skills.length ? `<div class="bad">missing ${esc(c.missing_skills.join(", "))}</div>` : ""}</td></tr>`).join("");
    const loc = w.location;
    const parts = w.parts.lines.map((l) => `<tr><td><b>${esc(l.part_number)}</b><div class="muted">${esc(l.description)}</div></td><td>${l.qty}</td><td>${esc(l.pick_type)}<div class="muted">${esc(l.pick)}</div></td><td>${usd(l.unit_price * l.qty)}</td></tr>`).join("");
    const appr = w.approvals.map((x, i) => `<div class="appr"><div><b>${esc(x.action)}</b> <span class="muted">${esc(x.rule)}</span></div>${x.outcome === "human" ? `<button class="btn small amber" data-approve="${i}">Approve · ${esc(x.approver)}</button>` : `<span class="ok">${esc(x.approver)}</span>`}</div>`).join("");
    const feed = (state.feed[w.work_order_id] || []).map((f) => `<div><span class="muted">+${(f.t / 3600).toFixed(1)}h</span> ${esc(f.text)}</div>`).join("");
    const inTransit = state.queue.filter((q) => q.wo === w.work_order_id && q.dir === "up" && q.status !== "synced").length;
    const telAge = telemetryAgeForSupervisor();
    return `<h3 style="margin-top:22px">${esc(w.work_order_id)} · ${esc(a.asset_id)}</h3>
      <div class="sub">${esc(a.category)} · ${esc(a.site_name)} · criticality ${esc(a.criticality)} · site coverage <b>${esc(a.coverage)}</b></div>
      ${!d.safe_to_run ? `<div class="safety">${d.safety_override ? "Unsafe to run: edge safety rule fired. Agents cannot override this." : "Unsafe to run: shutdown recommended."}</div>` : ""}
      <h3><span><span class="wf">W1</span> Diagnosis</span>${p1.html}</h3><div class="sub">Ranked by the repair recommendation model <b>${esc(RM.version)}</b> · ${pct(d.model_confidence || 0)} on the top cause · no tokens</div>${causesBlock(d.causes)}
      <h3><span><span class="wf">W2</span> Technician</span>${p2.html}</h3><table class="mini"><tr><th>Technician</th><th>Score</th><th>Drive</th><th>Status</th></tr>${techs}</table>
      <div class="sub">Needs: ${esc(w.skills_required.join(", "))} · est. ${w.est_hours} h</div>
      <h3><span><span class="wf">W3</span> Repair location</span>${p3.html}</h3>
      <div class="card"><b>${loc.location === "workshop" ? `Workshop (${esc(DEPOTS[loc.workshop_id]?.city || loc.workshop_id)})` : "On site"}</b> <span class="muted">· on-site ${loc.score_on_site} vs workshop ${loc.score_workshop}</span><div class="sub">${loc.factors.map((f) => `${esc(f.factor)} → ${esc(f.favors.replace("_", " "))}`).join(" · ")}</div>${loc.note ? `<div class="note">${esc(loc.note)}</div>` : ""}</div>
      <h3><span><span class="wf">W4</span> Parts</span>${p4.html}</h3><table class="mini"><tr><th>Part</th><th>Qty</th><th>Source</th><th>Cost</th></tr>${parts}</table><div class="sub">Total ${usd(w.parts.total_usd)}</div>
      <h3>Approvals <span class="muted" style="font-weight:400;font-size:12px">rule-based</span></h3>${appr}
      <h3>Live telemetry ${telAge === null ? '<span class="prov none">no data</span>' : `<span class="prov edge">Edge <span class="conf">· ${fmtAge(telAge)}</span></span>`}</h3>
      ${telemetryBlock(w.asset_id, telAge, "The site gateway isn't reporting. The technician falls back to guided inspection.")}
      <h3>Activity (as seen by the cloud)</h3><div class="feed">${feed}</div>
      ${inTransit ? `<div class="note">${inTransit} update${inTransit > 1 ? "s" : ""} from the field ${inTransit > 1 ? "are" : "is"} still in the technician's outbox.</div>` : ""}`;
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
  const myJobs = () => D.work_orders.filter((w) => state.techView[w.work_order_id]?.assigned === state.techId && state.techView[w.work_order_id].status !== "completed");
  const currentJob = () => (state.persona === "walkthrough" ? WT_WO : isField(state.persona) ? myJobs()[0] : null);

  function technicianPanel() {
    const t = TECHS[state.techId];
    const opts = D.technicians.map((x) => `<option value="${x.technician_id}" ${x.technician_id === state.techId ? "selected" : ""}>${esc(x.name)} · ${esc(DEPOTS[x.home_depot].city)}</option>`).join("");
    const jobs = myJobs();
    const pendingDown = state.queue.filter((q) => q.dir === "down" && q.status !== "synced" && q.payload.tech === state.techId).length;
    let body;
    if (!jobs.length) body = `<div class="empty">No assigned jobs on this device.${pendingDown ? `<br>${pendingDown} new assignment waiting for a connection.` : ""}<br><span class="sub">Approve a work order in the Supervisor view, or pick another technician.</span></div>`;
    else {
      const w = jobs[0], outN = state.queue.filter((q) => q.dir === "up" && q.status !== "synced").length;
      const tabs = [["plan", "Repair plan"], ["diagnose", "Diagnose"], ["pack", "Mission pack"], ["parts", "Parts"], ["telemetry", "Live data"], ["closeout", "Close out"], ["outbox", `Outbox (${outN})`]];
      body = `${jobCard(w)}<div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button class="tab ${state.techTab === k ? "active" : ""}" data-tab="${k}">${esc(l)}</button>`).join("")}</div>${techTab(w)}`;
    }
    return `<h2>My jobs</h2><div class="row" style="margin:6px 0 4px"><select id="tech-select" aria-label="Technician" style="flex:1">${opts}</select></div><div class="sub">Van ${esc(t.van_id)} · ${esc(t.skills.join(", "))}</div>${body}`;
  }
  function jobCard(w) {
    const a = ASSETS[w.asset_id], c = w.technicians.find((x) => x.technician_id === state.techId) || w.technicians[0];
    return `<div class="card"><div class="row"><b>${esc(w.work_order_id)}</b><span class="pill pri-${w.priority}">${esc(w.priority)}</span></div><div>${esc(w.title)}</div>
      <div class="sub">${esc(a.asset_id)} · ${esc(a.model)} · ${c.distance_km} km, about ${c.eta_min} min drive</div><div class="sub">${esc(a.access_notes)}${a.hazards.length ? ` · <b>Hazards:</b> ${esc(a.hazards.join("; "))}` : ""}</div></div>
      ${!w.diagnosis.safe_to_run ? `<div class="safety">Do not run this unit. ${w.diagnosis.safety_override ? "The edge safety rule tripped." : "Shutdown recommended."}</div>` : ""}`;
  }
  function planBlock(w, interactive = true) {
    const cached = state.plans[w.work_order_id];
    if (!cached) { loadPlan(w.work_order_id, state.persona === "walkthrough" ? "walkthrough" : "technician").then(render); return `<div class="empty">Loading the repair plan…</div>`; }
    const { plan, source, at } = cached, local = state.stepLocal[w.work_order_id] || {};
    const src = source === "db" ? `<span class="prov cloud">Repair DB <span class="conf">· v${plan.version} · ${fmtAge(Math.max(0, state.simOffset - at))}</span></span>` : `<span class="prov device">Mission pack copy <span class="conf">· ${state.api ? "synced at depot" : "embedded demo data"}</span></span>`;
    const PH = { safety: "Lockout / tagout", verify: "Verify the diagnosis", repair: "Repair", test: "Test run", closeout: "Close out" };
    const steps = Object.keys(PH).map((ph) => {
      const ss = plan.steps.filter((s) => s.phase === ph);
      return ss.length ? `<div class="phase"><div class="phase-h">${PH[ph]}</div>${ss.map((s) => {
        const st = local[s.seq] || (s.status === "done" ? "synced" : null);
        return `<label class="check step ${st ? "done" : ""}"><input type="checkbox" data-step="${s.seq}" ${st ? "checked disabled" : ""} ${interactive ? "" : "disabled"}><span>${esc(s.instruction)}${st ? `<span class="step-st ${st}">${st === "synced" ? "saved to DB" : "queued offline"}</span>` : ""}</span></label>`;
      }).join("")}</div>` : "";
    }).join("");
    const done = plan.steps.filter((s) => local[s.seq] || s.status === "done").length;
    const refs = plan.references.map((r) => `<details><summary>${esc(r.kind === "manual" ? "Manual" : r.kind === "asset_repair" ? "This compressor" : "Similar fix")} · ${esc(r.title)}</summary><pre>${esc(r.detail)}</pre></details>`).join("");
    return `<h3><span>Repair recommendation</span>${src}</h3>
      <div class="card"><b>${esc(plan.cause_description)}</b> <span class="muted">${esc(plan.cause_code)}</span><div class="sub">${esc(plan.generated_by)}${plan.model_confidence ? ` (${pct(plan.model_confidence)} confident)` : ""} · est. ${plan.est_hours} h · ${plan.repair_location === "workshop" ? "workshop job" : "on site"}</div>
        <div class="progress"><span style="width:${Math.round((done / plan.steps.length) * 100)}%"></span></div><div class="sub">${done} of ${plan.steps.length} steps done</div></div>
      ${steps}<h3>References in this plan</h3>${refs || '<div class="sub">None</div>'}`;
  }
  function techTab(w) {
    const a = ASSETS[w.asset_id], tab = state.techTab;
    if (tab === "plan") return planBlock(w);
    if (tab === "diagnose") {
      const p = provFor("diagnose_issue", "technician");
      if (state.sensorsLost) {
        const tr = (D.manuals[a.model] || []).filter((m) => m.title.startsWith("Troubleshooting"));
        const symOf = (m) => (m.text.match(/Typical symptoms: ([^.]*)\./) || ["", ""])[1].split("; ").filter(Boolean);
        const syms = [...new Set(tr.flatMap(symOf))], sel = state.inspection[w.work_order_id] || new Set();
        const ranked = rmPredict(a.model, null, null, [...sel]).map((r) => ({ code: r.cause_code, p: r.probability,
          title: r.cause_code === "HEALTHY" ? "No fault found" : (tr.find((m) => m.text.includes(`Fault code ${r.cause_code}.`))?.title || r.cause_code).replace("Troubleshooting: ", "") }));
        return `<h3><span><span class="wf">W1</span> Guided inspection</span><span class="prov device">Device <span class="conf">· ${esc(RM.version)} · sensors lost</span></span></h3>
          <div class="note">No live data from the site gateway. Tick what you observe; the device copy of the repair recommendation model re-ranks causes from your symptoms, with no network and no tokens.</div>
          ${syms.map((s) => `<label class="check"><input type="checkbox" data-sym="${esc(s)}" ${sel.has(s) ? "checked" : ""}><span>${esc(s)}</span></label>`).join("")}
          <h3>Likely causes</h3>${ranked.map((r) => `<div class="cause"><span>${esc(r.title)} <span class="muted">${esc(r.code)}</span></span><div class="bar"><span style="width:${Math.round(r.p * 100)}%"></span></div><b>${Math.round(r.p * 100)}%</b></div>`).join("")}`;
      }
      return `<h3><span><span class="wf">W1</span> Diagnosis</span>${p.html}</h3><div class="sub">${esc(p.why)}</div>${causesBlock(w.diagnosis.causes)}<h3>Evidence</h3>${w.diagnosis.evidence.map((e) => `<div class="sub">• ${esc(e)}</div>`).join("") || '<div class="sub">No alarms yet</div>'}`;
    }
    if (tab === "pack") {
      const hist = (D.history[a.asset_id] || []).slice(0, 5);
      return `<div class="note">Mission pack synced at the depot. Fully available offline.</div><h3>Manual: ${esc(a.model)}</h3>${(D.manuals[a.model] || []).map((m) => `<details><summary>${esc(m.title)}</summary><pre>${esc(m.text)}</pre></details>`).join("")}
        <h3>Past repairs on ${esc(a.asset_id)}</h3>${hist.length ? hist.map((h) => `<div class="card"><div class="row"><b>${esc(h.cause_code)}</b><span class="muted">${esc(h.date)}</span></div><div class="sub">${esc(h.notes)} · ${h.labor_hours} h · ${h.first_time_fix ? '<span class="ok">first-time fix</span>' : '<span class="bad">return visit</span>'}</div></div>`).join("") : '<div class="sub">No previous repairs</div>'}`;
    }
    if (tab === "parts") {
      const p = provFor("check_parts", "technician"), van = state.van[state.techId];
      const rows = w.parts.lines.map((l) => { const have = van[l.part_number] || 0; return `<tr><td><b>${esc(l.part_number)}</b><div class="muted">${esc(l.description)}</div></td><td>${l.qty}</td><td class="${have >= l.qty ? "ok" : "bad"}">${have}</td><td><button class="btn small ghost" data-use="${esc(l.part_number)}" ${have ? "" : "disabled"}>Use 1</button></td></tr>`; }).join("");
      const missing = w.parts.lines.filter((l) => (van[l.part_number] || 0) < l.qty);
      return `<h3><span><span class="wf">W4</span> Parts for this job</span>${p.html}</h3><div class="sub">${esc(p.why)}</div><table class="mini"><tr><th>Part</th><th>Need</th><th>In van</th><th></th></tr>${rows}</table>
        ${missing.length ? `<div class="note">Not in the van: ${missing.map((l) => `${esc(l.part_number)} from ${esc(l.pick_type)} ${esc(l.pick)}`).join(", ")}.</div>` : ""}
        <h3>Van stock</h3><table class="mini">${Object.entries(van).map(([pn, q]) => `<tr><td>${esc(pn)}</td><td>${q}</td></tr>`).join("")}</table>`;
    }
    if (tab === "telemetry") return `<h3>Live data <span class="prov edge">Edge <span class="conf">· local link</span></span></h3><div class="sub">Read straight from the site gateway over Wi-Fi/BLE, so it works with no WAN.</div>${telemetryBlock(a.asset_id, state.sensorsLost ? null : 5, "The site gateway isn't reporting. Use the guided inspection on the Diagnose tab and record readings by hand.")}`;
    if (tab === "closeout") return `<h3><span><span class="wf">W6</span> Close out</span></h3><label class="sub" for="co-cause">Confirmed cause</label>
        <select id="co-cause" style="width:100%;margin:4px 0 8px">${w.diagnosis.causes.map((c) => `<option value="${esc(c.cause_code)}">${esc(c.description)} (${esc(c.cause_code)})</option>`).join("")}</select>
        <label class="sub" for="co-notes">Findings</label><textarea id="co-notes" rows="3" style="width:100%;margin:4px 0 8px" placeholder="What you found and did"></textarea>
        <div class="row" style="justify-content:flex-start;gap:8px;flex-wrap:wrap"><button class="btn ghost" id="co-photo">Attach photo (3.2 MB)</button><button class="btn ghost" id="co-findings">Save findings</button><button class="btn amber" id="co-complete">Complete job</button></div>
        <div class="sub" style="margin-top:8px">Findings, steps and status are P1 and go out first. Photos are P4 and wait for Online.</div>`;
    const items = state.queue.filter((q) => q.dir === "up").slice().reverse();
    return `<h3>Outbox <span class="muted" style="font-weight:400;font-size:12px">sent in priority order when the link allows</span></h3>
      ${items.length ? items.map((q) => `<div class="outbox-item"><span class="prio ${q.prio}" title="${PRIO_LABEL[q.prio]}">${q.prio}</span><span>${esc(q.text)}<div class="muted">${esc(q.wo)}</div></span><span class="${q.status === "synced" ? "q-synced" : "q-queued"}">${q.status === "synced" ? "synced" : "queued"}</span></div>`).join("") : '<div class="empty">Nothing recorded yet</div>'}`;
  }

  function record(who, prio, wo, text, kind, payload = {}) {
    const tool = kind === "step" ? "repair_db.update_step" : kind === "complete" ? "repair_db.outcome" : "update_work_order";
    const p = callTool(tool, who, text);
    const q = enqueue("up", prio, wo, text, kind, payload);
    if (kind === "step") (state.stepLocal[wo] ||= {})[payload.seq] = q.status === "synced" ? "synced" : "queued";
    return { p, q };
  }
  function doStep(who, wo, seqNo, techId) {
    const s = state.plans[wo]?.plan.steps.find((x) => x.seq === seqNo);
    if (!s || (state.stepLocal[wo] || {})[seqNo]) return;
    record(who, s.phase === "safety" ? "P0" : "P1", wo, `Step ${seqNo} done: ${s.instruction.slice(0, 60)}${s.instruction.length > 60 ? "…" : ""}`, "step", { seq: seqNo, by: techId });
  }
  function completeJob(who, wo, cause, notes, techId) {
    record(who, "P1", wo, `Job complete, cause ${cause}`, "complete", { cause, notes, by: techId });
    state.techView[wo] = { ...(state.techView[wo] || {}), status: "completed", assigned: techId };
  }

  // ------------------------------------------------------------------ assistant
  const INTENTS = [
    ["safety", /safe|restart|run it|start it/i], ["diagnose", /wrong|cause|diagnos|fault|problem|issue/i],
    ["telemetry", /reading|live|telemetry|temperature|pressure|vibration|current|dew|sensor/i], ["parts", /part|stock|spare|van|filter|seal|kit/i],
    ["techs", /who|technician|help me|dispatch|assign|colleague/i], ["location", /where|workshop|on.?site|location/i],
    ["procedure", /how|fix|procedure|step|manual|repair|plan/i], ["history", /history|before|past|last time|similar/i],
    ["status", /sync|outbox|offline|queue|connection|network|signal/i],
  ];
  const contextWO = (who) => (who === "supervisor" ? WOS[state.selectedWO] : currentJob());
  function repairDone(w) {
    const plan = state.plans[w.work_order_id]?.plan, local = state.stepLocal[w.work_order_id] || {};
    return !!plan && plan.steps.filter((s) => s.phase === "repair").every((s) => local[s.seq] || s.status === "done");
  }
  function ask(q, who) {
    const w = contextWO(who), via = "assistant";
    if (!w) return pushChat(who, q, "There's no job selected. Pick a work order first.", null);
    const intent = (INTENTS.find(([, re]) => re.test(q)) || ["help"])[0];
    const a = ASSETS[w.asset_id], d = w.diagnosis, top = d.causes[0];
    let tool = null, answer = "";
    if (intent === "diagnose" || intent === "safety") {
      tool = callTool("diagnose_issue", who, q, { via });
      if (state.sensorsLost && isField(who)) answer = `No live data from the gateway. From the mission pack, start by checking ${top.description.toLowerCase()} (${top.cause_code}). Tick symptoms on the Diagnose tab and I'll re-rank.`;
      else if (intent === "safety" && isField(who) && repairDone(w)) answer = `Yes. The repair steps are done: remove your locks in reverse order, restart, and watch ${Object.keys(D.telemetry[a.asset_id].thresholds).slice(0, 2).join(" and ")} for 15 minutes (the test step).`;
      else if (intent === "safety") answer = d.safe_to_run ? `It can keep running while you prepare; likely ${top.description.toLowerCase()}. Restart after a repair only once the lockout steps are reversed and the test step is done.` : `No. ${d.safety_override ? "The edge safety rule tripped, and nobody can override that." : "Shutdown is recommended."} Keep it locked out until the repair and test steps are done.`;
      else answer = `The repair recommendation model says most likely ${top.description.toLowerCase()} (${pct(top.probability)}), then ${d.causes[1].description.toLowerCase()} (${Math.round(d.causes[1].probability * 100)}%). ${d.safe_to_run ? "Safe to keep running for now." : "Do not run it."} Evidence: ${d.evidence[0] || "reported symptoms"}.`;
    } else if (intent === "telemetry") {
      tool = callTool("get_live_telemetry", who, q, { via });
      if (tool.status === "failed") answer = "The site gateway isn't reporting, so there are no live readings. Take manual readings and log them in your findings.";
      else { const T = D.telemetry[a.asset_id]; answer = T.series.slice(0, 4).map((s) => { const th = T.thresholds[s.signal], v = s.points.at(-1).value; const bad = th.warn != null && (th.low_is_bad ? v <= th.warn : v >= th.warn); return `${s.signal} ${v.toFixed(1)} ${s.unit}${bad ? " (over limit)" : ""}`; }).join("; ") + `.${tool.status === "stale" ? " These are last known values." : ""}`; }
    } else if (intent === "parts") {
      tool = callTool("check_parts", who, q, { via });
      const van = isField(who) ? state.van[state.techId] : {};
      answer = w.parts.lines.map((l) => isField(who) ? `${l.part_number} (${l.description}): ${(van[l.part_number] || 0) >= l.qty ? "in your van" : `not in your van, ${tool.tier === "device" ? "can't check depot stock offline" : `get it from ${l.pick_type} ${l.pick}`}`}` : `${l.part_number}: ${l.qty} from ${l.pick_type} ${l.pick}`).join(". ") + ".";
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
      answer = h.length ? h.map((r) => `${r.date}: ${r.cause_code}, ${r.labor_hours} h, ${r.first_time_fix ? "fixed first time" : "needed a return visit"}`).join(". ") + "." : "No earlier repairs on this compressor.";
    } else {
      const p = callTool("local_status", who, q, { via });
      if (intent === "status") {
        const n = state.queue.filter((x) => x.status !== "synced").length;
        return pushChat(who, q, `You're ${mode().name.toLowerCase()}${state.aiDown ? " (cloud AI outage)" : ""}. ${n ? `${n} update${n > 1 ? "s" : ""} waiting; safety (P0) and job updates (P1) go first when the link allows, photos last.` : "Everything is synced."}`, p, null);
      }
      return pushChat(who, q, "I can help with: what's wrong, is it safe, live readings, parts, who else could help, where to repair, how to fix it, past repairs, and sync status.", p, null);
    }
    const comp = callTool("compose_answer", who, `Write answer: "${q}"`, { via });
    return pushChat(who, q, answer, comp, tool);
  }
  function pushChat(who, q, a, comp, tool) {
    const ms = (comp?.ms || 0) + (tool?.ms || 0), tok = (comp?.tin || 0) + (comp?.tout || 0) + (tool?.tin || 0) + (tool?.tout || 0);
    const foot = comp ? `${PLACE[comp.tier]}${comp.model ? ` · ${comp.model}` : ""} · ${fmtMs(ms)} · ${fmtTok(tok)} tokens` : "";
    const msg = { who, q, a, foot, tier: comp?.tier || "device" };
    state.chat.push(msg); renderAssistant();
    return msg;
  }
  const suggestions = () => (state.persona === "supervisor" ? ["What's wrong with it?", "Who should go?", "Do we have the parts?", "On site or workshop?"] : ["What's wrong with this unit?", "Show me live readings", "Do I have the parts?", "How do I fix it?", "Is it safe to restart?", "What's my sync status?"]);
  function renderAssistant() {
    $("#assistant").hidden = !state.assistantOpen; $("#ask-fab").hidden = state.assistantOpen;
    if (!state.assistantOpen) return;
    const w = contextWO(state.persona);
    $("#as-context").textContent = w ? `${w.work_order_id} · ${ASSETS[w.asset_id].model} · ${PERSONA_NAME[state.persona]} · ${modeLabel()}` : "No job selected";
    const msgs = state.chat.filter((m) => m.who === state.persona || (state.persona === "technician" && m.who === "walkthrough")).slice(-8);
    $("#as-msgs").innerHTML = msgs.length ? msgs.map((m) => `<div class="msg q">${esc(m.q)}</div><div class="msg a">${esc(m.a)}${m.foot ? `<div class="foot"><span class="dot-t ${m.tier}"></span>${esc(m.foot)}</div>` : ""}</div>`).join("") : `<div class="sub" style="padding:8px 2px">Ask about the selected job. Each answer shows where it ran and what it cost; every request appears in the live panel.</div>`;
    $("#as-msgs").scrollTop = 1e6;
    $("#as-chips").innerHTML = suggestions().map((s) => `<button class="as-chip" data-ask="${esc(s)}">${esc(s)}</button>`).join("");
  }

  // ------------------------------------------------------------------ live panel
  function renderLive(flashId) {
    const Lg = state.log, tot = { n: Lg.length, ms: 0, cloud: 0, edge: 0, device: 0, local: 0 };
    for (const e of Lg) { tot.ms += e.ms; if (e.tier in tot) tot[e.tier] += e.tin + e.tout; if (e.tier === "edge" || e.tier === "device") tot.local += 1; }
    const pct = tot.n ? Math.round((tot.local / tot.n) * 100) : 0;
    const counts = {}; Lg.forEach((e) => (counts[e.tier] = (counts[e.tier] || 0) + 1));
    const bar = Object.entries(counts).map(([t, n]) => `<span class="lb ${t}" style="flex:${n}" title="${PLACE[t]}: ${n}"></span>`).join("");
    $("#live-totals").innerHTML = `<span><b>${tot.n}</b> requests</span><span><b>${fmtMs(tot.ms)}</b> total</span>
      <span>tokens: <b class="t-cloud">${fmtTok(tot.cloud)}</b> cloud · <b class="t-edge">${fmtTok(tot.edge)}</b> edge · <b class="t-device">${fmtTok(tot.device)}</b> device</span><span><b>${pct}%</b> ran on edge or device</span><span class="lbar" aria-hidden="true">${bar}</span>`;
    if (!state.liveOpen) return;
    const who = (e) => (e.who === "outbox" ? "Outbox" : PERSONA_NAME[e.who] || e.who) + (e.via ? " · assistant" : "");
    $("#live-rows").innerHTML = Lg.slice(-60).reverse().map((e) => `<div class="live-row ${e.id === flashId ? "flash" : ""} st-${e.status}">
      <span class="muted">+${(e.t / 3600).toFixed(1)}h</span><span>${esc(who(e))}</span><span class="req">${esc(e.request)}</span><span class="mono">${esc(e.tool)}</span>
      <span><span class="prov ${e.tier}">${PLACE[e.tier]}${e.model ? ` <span class="conf">· ${esc(e.model)}</span>` : ""}</span>${e.status === "queued" ? ' <span class="q-queued">queued</span>' : e.status === "failed" ? ' <span class="bad">failed</span>' : e.status === "stale" ? ' <span class="q-queued">stale</span>' : ""}</span>
      <span class="why">${esc(e.why)}</span><span class="r">${fmtMs(e.ms)}</span><span class="r">${e.tin + e.tout ? `${fmtTok(e.tin)} in / ${fmtTok(e.tout)} out` : '<span class="muted">0</span>'}</span></div>`).join("") || `<div class="empty">No requests yet. Pick a work order, open a tab, or ask the assistant.</div>`;
  }

  // ------------------------------------------------------------------ walkthrough persona
  const WT = { idx: -1, running: false, notes: {}, auto: false };
  function wtSteps() {
    const w = WT_WO, a = ASSETS[w.asset_id], t = TECHS[w.assigned_technician_id], n = firstName(t.technician_id), van = state.van[t.technician_id];
    const missing = w.parts.lines.filter((l) => (van[l.part_number] || 0) < l.qty);
    const S = (time, mode, ev, pos, title, story, run) => ({ time, mode, ev, pos, title, story, run });
    const who = "walkthrough", wo = w.work_order_id;
    const say = async (i, q) => { const m = ask(q, who); (WT.notes[i] ||= []).push({ q, a: m.a, foot: m.foot }); await sleep(500); };
    const did = (i, text) => (WT.notes[i] ||= []).push({ did: text });
    const plan = () => state.plans[wo].plan, stepsOf = (ph) => plan().steps.filter((s) => s.phase === ph);
    return [
      S("07:30", "ONLINE", {}, 0, "At the depot", `${n} gets ${wo} on the tablet: ${a.category} at ${a.site_name}. The mission pack and the repair recommendation sync from the cloud over depot Wi-Fi.`, async (i) => {
        await loadPlan(wo, who, `Download repair plan ${wo}`); did(i, `Repair plan v${plan().version} copied from the cloud DB into the mission pack DB (${plan().steps.length} steps)`);
        callTool("sync_mission_pack", who, `Mission pack for ${a.asset_id}: manuals, history, plan (4.2 MB)`); did(i, "Mission pack downloaded (P3, depot Wi-Fi)"); await sleep(400);
        await say(i, "What's wrong with this unit?");
      }),
      S("08:15", "LIMITED", {}, 0.4, "On the highway, weak signal", `One bar of LTE. Diagnosis moves to the edge model; the cloud is used only when a window opens.`, async (i) => {
        await say(i, "Do I have the parts?");
        did(i, missing.length ? `Missing ${missing.map((l) => l.part_number).join(", ")}: picked up at the depot on the way` : "All parts are in the van");
        await say(i, "Who else could help if I get stuck?");
      }),
      S("09:45", "OFFLINE", {}, 1, "On site, no coverage", `No WAN at all. ${n} reads the compressor over the gateway's local link; the edge model answers questions, and the lockout follows the plan in the mission pack DB.`, async (i) => {
        await say(i, "Show me live readings");
        await say(i, "How do I fix it?");
        for (const s of stepsOf("safety")) { doStep(who, wo, s.seq, t.technician_id); await sleep(120); }
        did(i, `Lockout steps 1–${stepsOf("safety").length} done (P0, queued in the outbox)`);
      }),
      S("10:30", "OFFLINE", { sensorsLost: true }, 1, "Repair, gateway powered down", `With the compressor isolated, the site gateway goes dark too. The device model takes over; the repair continues from the plan.`, async (i) => {
        const seen = (w.diagnosis.evidence.find((e) => e.startsWith("Reported: ")) || "").replace("Reported: ", "").split("; ").filter(Boolean);
        const rr = rmPredict(a.model, null, null, seen.length ? seen : [cat0(w)]);
        callTool("diagnose_issue", who, `Confirm cause from observed symptoms (${seen.length || 1})`);
        did(i, `Device copy of ${RM.version} re-ranked from symptoms only: ${rr[0].cause_code} ${Math.round(rr[0].probability * 100)}%, no network, 0 tokens`);
        for (const s of [...stepsOf("verify"), ...stepsOf("repair")]) { doStep(who, wo, s.seq, t.technician_id); await sleep(120); }
        for (const l of w.parts.lines) if ((van[l.part_number] || 0) > 0) { van[l.part_number] -= 1; record(who, "P1", wo, `Used 1 × ${l.part_number} from van`, "parts"); }
        await say(i, "Is it safe to restart?");
        did(i, "Diagnosis confirmed; repair steps done (P1, queued)");
      }),
      S("11:00", "OFFLINE", {}, 1, "Test run and close out", `Power back on site: the edge watches the test run. Findings, a photo and the completed job wait in the outbox.`, async (i) => {
        for (const s of stepsOf("test")) doStep(who, wo, s.seq, t.technician_id);
        await say(i, "Show me live readings");
        record(who, "P1", wo, `Findings: ${w.diagnosis.causes[0].cause_code} confirmed, parts replaced, test run OK`, "findings");
        record(who, "P4", wo, "Photo of the replaced part (3.2 MB)", "photo");
        for (const s of stepsOf("closeout")) doStep(who, wo, s.seq, t.technician_id);
        completeJob(who, wo, w.diagnosis.causes[0].cause_code, "Repaired per plan, test run OK", t.technician_id);
        await say(i, "What's my sync status?");
      }),
      S("12:10", "LIMITED", {}, 0.6, "Driving out, a window opens", `The first coverage window sends safety records and job updates to the cloud DB. The photo waits for Online.`, async (i) => {
        syncTick(false, true); await sleep(500); syncTick(false, true);
        did(i, `${state.queue.filter((q) => q.status === "synced").length} updates written to the cloud DB; photo still waiting (P4)`);
      }),
      S("13:00", "ONLINE", {}, 0.1, "Back online", `The photo uploads, the supervisor sees ${wo} completed, and the outcome is in the database for the next technician.`, async (i) => {
        syncTick(); await sleep(400);
        await loadPlan(wo, who, `Refresh plan ${wo} after sync`);
        did(i, `Cloud repair DB: ${plan().steps.filter((s) => s.status === "done").length || plan().steps.length} steps done, status ${plan().status || "completed"}`);
      }),
    ];
  }
  // first listed symptom of the top-ranked cause (used when nothing was reported)
  function cat0(w) { const m = (D.manuals[ASSETS[w.asset_id].model] || []).find((x) => x.text.includes(`Fault code ${w.diagnosis.causes[0].cause_code}.`)); return ((m?.text.match(/Typical symptoms: ([^;.]*)/) || ["", ""])[1]); }
  let WT_STEPS = null;
  async function runWtStep() {
    if (WT.running) return;
    WT_STEPS ||= wtSteps();
    if (WT.idx >= WT_STEPS.length - 1) return;
    WT.running = true; WT.idx += 1;
    const s = WT_STEPS[WT.idx], t = TECHS[WT_WO.assigned_technician_id], a = ASSETS[WT_WO.asset_id];
    state.techId = t.technician_id; state.simOffset = WT.idx * 1800 + 3600;
    state.sensorsLost = !!s.ev.sensorsLost; state.aiDown = !!s.ev.aiDown;
    state.techPos = [t.lat + (a.lat - t.lat) * s.pos, t.lon + (a.lon - t.lon) * s.pos];
    setMode(s.mode, true); render();
    try { await s.run(WT.idx); } finally { WT.running = false; }
    render();
    if (WT.auto && WT.idx < WT_STEPS.length - 1) { await sleep(1400); runWtStep(); } else WT.auto = false;
  }
  function walkthroughPanel() {
    WT_STEPS ||= wtSteps();
    const w = WT_WO, t = TECHS[w.assigned_technician_id];
    const steps = WT_STEPS.map((s, i) => {
      const notes = (WT.notes[i] || []).map((n) => n.did ? `<div class="wt-did">✓ ${esc(n.did)}</div>` : `<div class="msg q">${esc(n.q)}</div><div class="msg a">${esc(n.a)}<div class="foot">${esc(n.foot)}</div></div>`).join("");
      const m = MODES[s.mode];
      return `<div class="wt-step ${i === WT.idx ? "current" : i < WT.idx ? "done" : ""}"><div class="row"><b>${i + 1}. ${esc(s.title)}</b><span><span class="muted">${s.time}</span> <span class="pill" style="background:${m.color};color:${m.dark ? "var(--text)" : "#fff"}">${m.name}</span>${s.ev.sensorsLost ? ' <span class="pill ev">sensors lost</span>' : ""}</span></div>
        <div class="sub">${esc(s.story)}</div>${i <= WT.idx ? notes : ""}</div>`;
    }).join("");
    const done = WT.idx >= WT_STEPS.length - 1;
    return `<h2>${esc(t.name)} repairs ${esc(w.work_order_id)}</h2>
      <div class="sub">The assigned technician follows the repair recommendation from the database, through a dead zone and back. Watch the agents move in "Where agents run" and every request in the live panel.</div>
      <div class="row wt-controls"><button class="btn amber" id="wt-next" ${WT.running || done ? "disabled" : ""}>${WT.idx < 0 ? "Start" : "Next step"}</button><button class="btn ghost" id="wt-auto" ${WT.running || done ? "disabled" : ""}>Play all</button><button class="btn ghost" id="wt-restart">Restart demo</button></div>
      ${jobCard(w)}${steps}${WT.idx >= 0 && state.plans[w.work_order_id] ? `<h3>Live repair plan</h3>${planBlock(w, false)}` : ""}`;
  }

  // ------------------------------------------------------------------ banner + controls
  function banner() {
    const m = mode(), queued = state.queue.filter((q) => q.status !== "synced").length, ls = linkState();
    const ln = (label, st) => `<span>${label}: <span class="${st === "down" ? "link-down" : st === "flaky" ? "link-flaky" : "link-up"}">${st === "flaky" ? "in windows" : st}</span></span>`;
    $("#mode-banner").style.background = `color-mix(in srgb, ${m.color} 14%, white)`;
    $("#mode-banner").innerHTML = `<span class="badge" style="background:${m.color};${m.dark ? "color:var(--text)" : ""}">${m.name}</span>
      ${state.aiDown ? '<span class="badge ev">Cloud AI outage</span>' : ""}${state.sensorsLost ? '<span class="badge ev">Sensors lost</span>' : ""}<span>${esc(m.desc)}.</span>
      <span class="links">${ln("Device↔cloud", ls["device-cloud"])}${ln("Edge↔cloud", ls["edge-cloud"])}${ln("Device↔edge", ls["device-edge"])}${ln("Cloud AI", state.aiDown ? "down" : "up")}</span>
      ${queued ? `<span><b>${queued}</b> message${queued > 1 ? "s" : ""} waiting to sync</span>` : ""}<span class="api-chip ${state.api ? "on" : ""}">${state.api ? "Repair DB connected" : "Repair DB: embedded data"}</span>`;
    $("#mode-chips").innerHTML = Object.entries(MODES).map(([k, v]) => `<button role="radio" aria-checked="${k === state.mode}" class="mode-chip ${k === state.mode ? "active" : ""} ${v.dark ? "dark-text" : ""}" style="background:${v.color}" data-mode="${k}" title="${esc(v.desc)}">${v.name}</button>`).join("");
    $("#ev-ai").checked = state.aiDown; $("#ev-sensors").checked = state.sensorsLost;
    $("#sim-clock").textContent = fmtTime(simNow());
  }
  function setMode(m, fromScenario = false) {
    const on = (x) => MODES[x].cloud !== "down", was = on(state.mode);
    state.mode = m;
    if (was && !on(m)) state.offlineSince = state.simOffset;
    if (m === "ONLINE") state.offlineSince = null;
    state.agentAt = {};          // agents return to this mode's default places, then move with requests
    if (!fromScenario) stopScenario();
    syncTick(); render();
  }
  function setPersona(p) {
    state.persona = p;
    document.querySelectorAll(".persona-btn").forEach((b) => b.classList.toggle("active", b.dataset.persona === p));
    if (p === "walkthrough") state.techId = WT_WO.assigned_technician_id;
    render(); focusMap();
  }
  function scenarioUI() { $("#scenario-select").innerHTML = `<option value="">Manual (no scenario)</option>` + D.scenarios.map((s) => `<option value="${s.name}">${esc(s.name.replaceAll("_", " "))}</option>`).join(""); }
  function drawScenarioBar() {
    const s = D.scenarios.find((x) => x.name === state.scenario), bar = $("#scenario-bar");
    if (!s) { bar.innerHTML = ""; $("#scenario-note").textContent = ""; return; }
    bar.innerHTML = s.segments.map((g, i) => {
      const end = s.segments[i + 1]?.start_s ?? s.duration_s, ev = g.sensors_lost || g.cloud_ai_down;
      return `<div class="seg" title="${MODES[g.mode].name}${g.sensors_lost ? " + sensors lost" : ""}${g.cloud_ai_down ? " + cloud AI outage" : ""} ${esc(g.note)}" style="width:${((end - g.start_s) / s.duration_s) * 100}%;background:var(--${g.mode.toLowerCase()})${ev ? ";background-image:repeating-linear-gradient(45deg,transparent 0 4px,rgba(122,90,166,.75) 4px 7px)" : ""}"></div>`;
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
      if (seg.mode !== state.mode || seg.sensors_lost !== state.sensorsLost || seg.cloud_ai_down !== state.aiDown) {
        state.sensorsLost = seg.sensors_lost; state.aiDown = seg.cloud_ai_down; setMode(seg.mode, true);
      } else { syncTick(); banner(); drawScenarioBar(); }
    }, 250);
  }

  // ------------------------------------------------------------------ render + events
  function render() {
    banner(); kpis(); drawScenarioBar();
    const panel = $("#panel"), top = panel.scrollTop;
    panel.innerHTML = state.persona === "supervisor" ? supervisorPanel() : state.persona === "technician" ? technicianPanel() : walkthroughPanel();
    panel.scrollTop = top;
    if (state.persona === "walkthrough") panel.querySelector(".wt-step.current")?.scrollIntoView({ block: "nearest" });
    if (state.view === "topo") renderTopo(); else drawMap();
    renderAssistant(); renderLive();
  }
  const TAB_TOOL = { plan: "repair_db.get_plan", diagnose: "diagnose_issue", pack: "search_knowledge", parts: "check_parts", telemetry: "get_live_telemetry" };
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-persona],[data-mode],[data-view],[data-wo],[data-approve],[data-tab],[data-use],[data-ask],#co-photo,#co-findings,#co-complete,#scenario-play,#ask-fab,#as-close,#live-toggle,#live-clear,#wt-next,#wt-auto,#wt-restart");
    if (!t) return;
    if (t.dataset.persona) return setPersona(t.dataset.persona);
    if (t.dataset.mode) return setMode(t.dataset.mode);
    if (t.dataset.view) return setView(t.dataset.view);
    if (t.dataset.wo) return selectWO(t.dataset.wo);
    if (t.dataset.approve) return approve(WOS[state.selectedWO], Number(t.dataset.approve));
    if (t.dataset.tab) {
      state.techTab = t.dataset.tab;
      const w = myJobs()[0];
      if (TAB_TOOL[t.dataset.tab] && w) { if (t.dataset.tab === "plan") loadPlan(w.work_order_id, "technician").then(render); else callTool(TAB_TOOL[t.dataset.tab], "technician", `Open ${t.textContent.trim()} for ${w.work_order_id}`); }
      return render();
    }
    if (t.dataset.use) { const pn = t.dataset.use, w = myJobs()[0]; state.van[state.techId][pn] -= 1; record("technician", "P1", w.work_order_id, `Used 1 × ${pn} from van`, "parts"); return render(); }
    if (t.dataset.ask) { ask(t.dataset.ask, state.persona); return render(); }
    if (t.id === "co-photo") { record("technician", "P4", myJobs()[0].work_order_id, "Photo of failed component (3.2 MB)", "photo"); return render(); }
    if (t.id === "co-findings") { const notes = $("#co-notes").value.trim(); record("technician", "P1", myJobs()[0].work_order_id, `Findings: ${$("#co-cause").value}${notes ? ` · ${notes}` : ""}`, "findings"); return render(); }
    if (t.id === "co-complete") { const w = myJobs()[0]; completeJob("technician", w.work_order_id, $("#co-cause").value, $("#co-notes").value.trim(), state.techId); state.techTab = "plan"; return render(); }
    if (t.id === "scenario-play") return playScenario();
    if (t.id === "ask-fab") { state.assistantOpen = true; renderAssistant(); $("#as-input").focus(); return; }
    if (t.id === "as-close") { state.assistantOpen = false; return renderAssistant(); }
    if (t.id === "live-toggle") { state.liveOpen = !state.liveOpen; $("#live").classList.toggle("collapsed", !state.liveOpen); t.setAttribute("aria-expanded", state.liveOpen); setTimeout(() => { map.invalidateSize(); layoutTopo(); }, 50); return renderLive(); }
    if (t.id === "live-clear") { state.log = []; return renderLive(); }
    if (t.id === "wt-next") return runWtStep();
    if (t.id === "wt-auto") { WT.auto = true; return runWtStep(); }
    if (t.id === "wt-restart") return location.reload();
  });
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t.id === "tech-select") { state.techId = t.value; state.techTab = "plan"; render(); focusMap(); }
    else if (t.id === "ev-ai") { state.aiDown = t.checked; state.agentAt = {}; stopScenario(); render(); }
    else if (t.id === "ev-sensors") { state.sensorsLost = t.checked; state.agentAt = {}; stopScenario(); render(); }
    else if (t.id === "scenario-select") { stopScenario(); state.scenario = t.value || null; state.scenarioT = 0; drawScenarioBar(); }
    else if (t.dataset.step) { doStep("technician", myJobs()[0].work_order_id, Number(t.dataset.step), state.techId); render(); }
    else if (t.dataset.sym !== undefined) { const w = myJobs()[0], set = (state.inspection[w.work_order_id] ||= new Set()); t.checked ? set.add(t.dataset.sym) : set.delete(t.dataset.sym); callTool("diagnose_issue", "technician", `Re-rank causes from ${set.size} observed symptom${set.size === 1 ? "" : "s"}`); render(); }
  });
  $("#as-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("#as-input").value.trim();
    if (!v) return;
    $("#as-input").value = ""; ask(v, state.persona); render();
  });

  setInterval(() => syncTick(), 1500);
  scenarioUI();
  (async () => { try { const r = await fetch("/api/health"); state.api = r.ok && (await r.json()).ok === true; } catch { state.api = false; } render(); })();
  setView("topo");
  selectWO(state.selectedWO);
})();
