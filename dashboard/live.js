/* hybrid-ai Live: drives the real device backend (/api/*) and shows what actually happened. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const PLACE = { cloud: "Cloud", edge: "Edge", device: "Device" };
  const MODE_NAME = { ONLINE: "Online", LIMITED: "Limited", OFFLINE: "Offline" };
  let S = null, plan = null, lastDiag = null, busy = false, lastHit = null;

  async function api(path, body) {
    const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    return r.json();
  }
  const call = (tool, args = {}, request = "") => api("/api/call", { tool, args, request });

  // ---------------------------------------------------------------- rendering
  function linkCls(l) { return !l ? "down" : !l.up ? "down" : ""; }
  function render() {
    if (!S) return;
    const d = S.detected, net = S.net || { links: {} }, L = net.links || {};
    const dots = (arr) => arr.map((p) => `<span class="probe ${p.ok ? "ok" : "bad"}" title="${p.ok ? p.ms + " ms" : esc(p.error)}"></span>`).join("");
    const lastCloud = d.cloud[d.cloud.length - 1];
    $("#det").innerHTML = `Network set to <b>${MODE_NAME[net.mode] || "?"}</b>${net.sensors_lost ? " + sensors lost" : ""}${S.cloud?.ai_down ? " + cloud AI outage" : ""}
      · the device <b>detects ${MODE_NAME[d.mode]}</b> from its own probes: cloud ${dots(d.cloud)} ${lastCloud?.ok ? lastCloud.ms + " ms" : "no answer"} · edge ${dots(d.edge)}`;
    document.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("active", b.dataset.mode === net.mode));
    $("#sensors").checked = !!net.sensors_lost; $("#ai").checked = !!S.cloud?.ai_down;

    // links: device-edge (local), edge-cloud (WAN), device-cloud (WAN, drawn as an arc)
    const lt = (k) => { const l = L[k]; return l ? `${l.up ? `up · ${l.latency_ms} ms` : "down"} · ${l.accepted} ok / ${l.refused + l.cut} blocked` : "?"; };
    const flap = net.mode === "LIMITED";
    for (const [id, k] of [["de", "device-edge"], ["ec", "edge-cloud"], ["dc", "device-cloud"]]) {
      const el = $(`#l-${id}`), l = L[k];
      el.className = (id === "dc" ? "wan " : "link ") + (!l || !l.up ? "down" : flap && k !== "device-edge" ? "flap" : "");
      const t = $(`#t-${id}`);
      t.textContent = id === "dc" ? `device ↔ cloud (WAN): ${!l ? "?" : l.up ? `${l.latency_ms} ms` : "down"}` : !l ? "?" : l.up ? `${l.latency_ms} ms` : "down";
      el.title = `${k.replace("-", " ↔ ")}: ${lt(k)}`;
    }
    const zones = document.querySelectorAll(".place");
    if (zones.length === 3) {
      const box = $("#places").getBoundingClientRect(), r = [...zones].map((z) => z.getBoundingClientRect());
      const place = (el, a, b) => { el.style.left = `${a.right - box.left}px`; el.style.width = `${b.left - a.right}px`; };
      place($("#l-de"), r[0], r[1]); place($("#l-ec"), r[1], r[2]);
    }

    const job = S.device.job;
    $("#job").textContent = `${S.device.technician} · ${job.work_order_id} · ${job.title}`;
    const kv = (k, v) => `<div class="kv"><span>${esc(k)}</span><span>${esc(v)}</span></div>`;
    const tools = (list, place) => `<div class="tools">${list.map((t) => `<code class="${lastHit && lastHit.place === place && lastHit.tool === t ? "hit" : ""}">${t}</code>`).join("")}</div>`;
    const c = S.cloud, e = S.edge, dv = S.device, ob = dv.outbox, queued = ob.filter((o) => o.status === "queued").length;
    $("#h-cloud").textContent = c ? `MCP server · process up${c.ai_down ? " · AI outage" : ""}` : "process not answering";
    $("#b-cloud").innerHTML = c ? `<div class="lbl">Databases (live values)</div>
      ${kv("Repair recommendations DB", `${c.plans} plans · ${c.steps_done} steps done`)}${kv("Completed work orders", c.completed.join(", ") || "none")}
      ${kv("Telemetry features from the edge", `${c.features_received} received`)}${kv("Parts reservations", c.reservations)}
      <div class="lbl">MCP tools</div>${tools(["diagnose_issue", "find_technicians", "recommend_repair_location", "check_parts", "reserve_parts", "get_repair_plan", "update_step", "record_outcome", "recommend_repair", "explain", "ingest_features"], "cloud")}` : "";
    $("#h-edge").textContent = e ? "MCP server · process up" : "process not answering";
    $("#b-edge").innerHTML = e ? `<div class="lbl">Data (live values)</div>
      ${kv("Telemetry files (JSONL)", e.telemetry_files)}${kv("Features pushed to the cloud", e.features_pushed)}${kv("Buffered (waiting for the WAN)", e.buffered)}
      <div class="lbl">MCP tools</div>${tools(["get_live_telemetry", "diagnose_issue", "find_technicians", "check_parts", "recommend_repair", "explain"], "edge")}` : "";
    $("#h-device").textContent = "router · link monitor · process up";
    $("#b-device").innerHTML = `<div class="lbl">Databases (live values)</div>
      ${kv("Mission pack DB", dv.mission_pack.length ? `plan ${dv.mission_pack[0].work_order_id} · synced` : "empty (waiting for the cloud)")}
      ${kv("Outbox", `${queued} queued · ${ob.length - queued} synced`)}${kv("Van stock", `${Object.values(dv.van).reduce((a, b) => a + b, 0)} parts`)}
      <div class="lbl">Local tools</div>${tools(["diagnose_issue", "check_parts", "get_repair_plan", "recommend_repair_location", "search_knowledge", "recommend_repair", "explain"], "device")}`;
    $("#p-cloud").classList.toggle("down", !L["device-cloud"]?.up);
    $("#p-edge").classList.toggle("down", !L["device-edge"]?.up);
    for (const p of ["cloud", "edge", "device"]) $(`#p-${p}`).classList.toggle("hit", !!lastHit && lastHit.place === p && Date.now() - lastHit.at < 2500);

    $("#outbox").innerHTML = ob.length ? ob.slice(0, 12).map((o) => `<div class="ob"><span class="prio ${o.prio}">${o.prio}</span><span>${esc(o.label)}</span>
      <span class="${o.status === "synced" ? "q-synced" : "q-queued"}">${o.status}${o.attempts > 1 ? ` (${o.attempts} tries)` : ""}</span></div>`).join("") : '<div class="sub">Empty</div>';

    $("#log").innerHTML = S.log.slice().reverse().map((x) => `<tr>
      <td class="muted">${esc(x.t.slice(11, 19))}</td><td>${esc(x.request)}<div class="muted">${esc(x.who)}</div></td><td><code>${esc(x.tool)}</code></td>
      <td class="att">${x.attempts.map((a) => `${PLACE[a.place]} <span class="${a.ok ? "v" : "x"}">${a.ok ? "✓" : "✗"}</span> ${a.ms} ms${a.error ? `<span class="err">${esc(a.error)}</span>` : ""}`).join(" → ") || `<span class="muted">${x.status === "queued" ? "no WAN: straight to the outbox" : "no place can answer offline"}</span>`}</td>
      <td>${x.place ? `<span class="prov ${x.place}">${PLACE[x.place]}</span>` : '<span class="prov none">failed</span>'}${x.status === "queued" ? ' <span class="q-queued">queued</span>' : ""}</td>
      <td class="muted">${esc(x.why)}</td><td>${x.ms} ms</td></tr>`).join("");
  }

  async function refresh() {
    try { S = await api("/api/state"); render(); } catch { $("#det").textContent = "Device backend not reachable. Start it with: PYTHONPATH=src .venv/bin/python -m hybrid_ai.live"; }
  }

  // ---------------------------------------------------------------- actions
  function summary(x) {
    if (!x.result) return x.why;
    const r = x.result;
    if (r.causes) return `${PLACE[x.place]} (${r.inputs}): ${r.causes.map((c) => `${c.cause_code} ${Math.round(c.probability * 100)}%`).join(", ")}`;
    if (r.latest) return `${PLACE[x.place]}: ${Object.entries(r.latest).map(([k, v]) => `${k} ${v.value} ${v.unit}`).join(", ")}`;
    if (r.candidates) return `${PLACE[x.place]} (${r.freshness}): ${r.candidates.map((c) => c.name).join(", ")}`;
    if (r.lines) return `${PLACE[x.place]} (${r.freshness}): ${r.lines.map((l) => l.part_number + (l.in_van !== undefined ? ` ×${l.in_van} in van` : "")).join(", ")}`;
    if (r.plan) return `${PLACE[x.place]}: plan with ${r.plan.steps.length} steps${r.copy_synced_at ? " (mission pack copy)" : " (cloud DB)"}`;
    if (r.mode) return `${PLACE[x.place]} · ${r.mode === "llm" ? r.model : "retrieval only, no LLM"}: recommendation below`;
    if (r.answer !== undefined) return `${PLACE[x.place]} · ${r.model}: ${r.answer}`;
    if (r.queued) return `Queued in the device outbox (key ${r.idempotency_key})`;
    return `${PLACE[x.place] || "?"}: ${JSON.stringify(r).slice(0, 120)}`;
  }
  async function act(name) {
    let x;
    if (name === "diagnose") x = await call("diagnose_issue", {}, "What's wrong with this unit?");
    else if (name === "telemetry") x = await call("get_live_telemetry", {}, "Show me live readings");
    else if (name === "techs") x = await call("find_technicians", {}, "Who else could help?");
    else if (name === "parts") x = await call("check_parts", {}, "Do I have the parts?");
    else if (name === "plan") { x = await call("get_repair_plan", {}, "Open the repair plan"); if (x.result?.plan) plan = { ...x.result.plan, next: plan?.next || 0 }; }
    else if (name === "step") {
      if (!plan) { const p = await call("get_repair_plan", {}, "Open the repair plan"); if (p.result?.plan) plan = { ...p.result.plan, next: 0 }; }
      if (!plan) return say("No repair plan on the device yet.");
      const s = plan.steps[plan.next] || plan.steps[plan.steps.length - 1];
      x = await call("update_step", { seq: s.seq, status: "done", by: "TEC-0001", phase: s.phase }, `Step ${s.seq} done: ${s.instruction.slice(0, 50)}`);
      plan.next = Math.min(plan.next + 1, plan.steps.length - 1);
    } else if (name === "ask") {
      const facts = lastDiag ? `Most likely ${lastDiag.cause_code} (${Math.round(lastDiag.probability * 100)}%). Follow the repair plan, lockout first.` : "Open the repair plan and start with lockout.";
      x = await call("explain", { question: "What should I do?", facts }, "Ask: what should I do?");
    } else if (name === "agent") {
      say("Asking the manual agent… (Claude can take 20–60 s; without it, retrieval answers instantly)");
      x = await call("recommend_repair", { question: "" }, "Manual agent: what's wrong and how do I fix it?");
      showAgent(x);
    } else if (name === "complete") {
      const cause = lastDiag?.cause_code || plan?.cause_code || "unknown";
      x = await call("record_outcome", { confirmed_cause: cause, by: "TEC-0001", notes: "Repaired per plan" }, `Complete job, cause ${cause}`);
    }
    if (x?.result?.causes) lastDiag = x.result.causes[0];
    lastHit = x?.place ? { place: x.place, tool: x.tool, at: Date.now() } : null;
    say(summary(x));
    await refresh();
    return x;
  }
  const say = (t) => { $("#story").textContent = t; };
  function showAgent(x) {
    const card = $("#agent-card"), r = x.result;
    card.hidden = false;
    if (!r) {
      $("#agent-meta").innerHTML = '<span class="prov none">failed</span>';
      $("#agent-answer").textContent = "No place could answer: " + (x.attempts.map((a) => `${PLACE[a.place]}: ${a.error || "ok"}`).join("; ") || x.why);
      $("#agent-sources").textContent = ""; $("#agent-steps").textContent = ""; return;
    }
    const tok = r.usage ? r.usage.input_tokens + r.usage.output_tokens : 0;
    const fell = x.attempts.filter((a) => !a.ok).map((a) => `${PLACE[a.place]}: ${a.error}`).join(" · ");
    $("#agent-meta").innerHTML = `<span class="prov ${x.place}">${PLACE[x.place]}</span> ${r.mode === "llm" ? esc(r.model) : "retrieval only (no LLM)"}
      · ${x.ms} ms · ${tok ? `${r.usage.input_tokens} in / ${r.usage.output_tokens} out tokens` : "0 tokens"}`;
    $("#agent-answer").textContent = r.answer + (r.reason ? `\n\n(${r.reason})` : "") + (fell ? `\n(tried first: ${fell})` : "");
    $("#agent-sources").innerHTML = r.citations.map((c) => `<code>${esc(c.doc_id)}</code> ${esc(c.title)}`).join("<br>") || "none";
    $("#agent-steps").innerHTML = r.tool_calls.map((t) => `<code>${esc(t.tool)}</code> ${esc(JSON.stringify(t.input))} → ${t.error ? "error: " + esc(t.error) : (t.results ?? "") + " result(s)"}`).join("<br>");
  }
  const setNet = (body) => api("/api/net", body).then(refresh);

  async function waitMode(m, ms = 25000) {
    const t = Date.now();
    while (Date.now() - t < ms) { await refresh(); if (S?.detected.mode === m) return true; await sleep(700); }
    return false;
  }
  async function story() {
    if (busy) return; busy = true; $("#story-btn").disabled = true;
    const step = async (text, fn) => { say(text); await sleep(1200); await fn(); await sleep(1500); };
    try {
      await setNet({ mode: "ONLINE", sensors_lost: false, cloud_ai_down: false });
      await step("1 · At the depot (Online): the device detects the cloud, copies the repair plan, and asks the cloud copy of the model.", async () => {
        await waitMode("ONLINE"); await act("plan"); await act("diagnose"); });
      await step("2 · Highway (Limited): the network now flaps. Once the device detects it, diagnosis runs on the edge, next to the data.", async () => {
        await setNet({ mode: "LIMITED" }); await waitMode("LIMITED"); await act("diagnose"); await act("techs"); });
      await step("3 · On site (Offline): the WAN is cut. Live readings come over the local link; lockout steps queue in the outbox.", async () => {
        await setNet({ mode: "OFFLINE" }); await waitMode("OFFLINE"); await act("telemetry");
        for (let i = 0; i < 3; i++) await act("step"); });
      await step("4 · Gateway dark (sensors lost): the edge stops answering, so the device copy of the model ranks causes from symptoms, and the manual agent answers from the mission pack.", async () => {
        await setNet({ sensors_lost: true }); await sleep(3500); await act("diagnose"); await act("agent"); await act("step"); await act("complete"); });
      await step("5 · Back online: the device detects the cloud again and the outbox replays to the cloud DB, safety steps first.", async () => {
        await setNet({ mode: "ONLINE", sensors_lost: false }); await waitMode("ONLINE");
        const t = Date.now();
        while (Date.now() - t < 20000) { await refresh(); if (!S.device.outbox.some((o) => o.status === "queued")) break; await sleep(800); }
      });
      say(`Done. Cloud DB: ${S.cloud.steps_done} steps done, completed: ${S.cloud.completed.join(", ") || "none"}. Every request above shows each place it tried and the real time it took.`);
    } finally { busy = false; $("#story-btn").disabled = false; }
  }

  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-mode],[data-act],#story-btn");
    if (!t || busy && t.id !== "story-btn") return;
    if (t.dataset.mode) setNet({ mode: t.dataset.mode });
    else if (t.dataset.act) act(t.dataset.act);
    else if (t.id === "story-btn") story();
  });
  $("#sensors").addEventListener("change", (e) => setNet({ sensors_lost: e.target.checked }));
  $("#ai").addEventListener("change", (e) => setNet({ cloud_ai_down: e.target.checked }));
  window.addEventListener("resize", render);
  refresh(); setInterval(() => { if (!busy) refresh(); }, 1200);
})();
