# 5-minute demo: run sheet

**Story in one line:** *a compressor fails at a remote site; the supervisor decides in seconds, the technician repairs it through a dead zone, and nothing is lost, because the agents move between cloud, edge and device.*

## Before you start (2 minutes, before the audience arrives)

1. Start the server with a fresh database. If you deployed the services (`deploy/install.sh`), they're already running: restart them for a fresh state with `systemctl --user restart hybrid-ai-dashboard hybrid-ai-live`. Otherwise:

   ```bash
   cd ~/hybrid-ai && PYTHONPATH=src python3 -m hybrid_ai.demo.server --port 8765 --reset
   ```

   For the optional live segment, also start the live demo in a second terminal (skip if deployed):

   ```bash
   cd ~/hybrid-ai && PYTHONPATH=src .venv/bin/python -m hybrid_ai.live
   ```

2. Open http://localhost:8765 in a browser window at least **1280 px wide** (full screen is best).
   - The banner should say **Online** and **Repair DB connected**.
   - The main view should be on **Where agents run**.
3. Open [hybrid-ai-brief.pptx](hybrid-ai-brief.pptx) in PowerPoint, ready on **slide 2**.
4. Rehearsing again? Stop the server (Ctrl+C) and rerun step 1. `--reset` rebuilds the database, and reloading the page resets the dashboard.

**If something goes wrong:**

| Problem | What to do |
|---|---|
| No internet | Map tiles won't load, but the **Where agents run** view and everything else works. Stay on that tab. |
| Server won't start | Run `python3 -m http.server 8765 --directory dashboard`. The dashboard uses its built-in plans; step updates just won't be written to the database. |

---

## The 5 minutes

### 0:00–0:45 · The problem (brief deck, slides 2–3)

- **Slide 2:** "We run 30 compressors at 12 remote California sites. Half of them have patchy or no coverage, and about 1 repair in 5 needs a second visit."
- **Slide 3:** "The hard part isn't the AI. It's that the signal disappears exactly where the work is, the cloud AI can fail too, and safety can't wait for a connection."

### 0:45–1:15 · The idea (brief deck, slide 5, the animated slide)

- Start **Slide Show** on slide 5 and click four times while you talk:
  - "Online: the agents and the model run in the cloud."
  - *Click.* "The link weakens: the work moves to the edge, next to the compressor's data."
  - *Click.* "No signal: the edge and the technician's tablet carry on."
  - *Click.* "The site loses power: the tablet takes over."
  - *Click.* "Back online: everything returns and syncs."
- Switch to the browser.

### 1:15–2:15 · Supervisor: decide fast (dashboard)

1. **Supervisor** tab. Click **WO-2026-0002** (urgent, two-stage reciprocating compressor).
2. Point at **W1 Diagnosis**: "A small trained model ranked the causes. It's 9 KB, uses no tokens, and the same file runs in the cloud, on the edge and on the tablet."
3. Point at W2 to W4: "Best technicians, on site or workshop, parts and cost, each labeled with where it ran and how fresh it is."
4. Under **Approvals**, click **Approve · Supervisor**: "Rules approve routine work. Only the decisions that need a person reach me."
5. Point at the **Live requests** panel at the bottom: "Every request: where it ran, why there, how long it took, and how many tokens it used."

### 2:15–4:00 · Technician: repair through a dead zone

1. Click **Assigned tech walkthrough** at the top right. Keep the main view on **Where agents run**.
2. Click **Play all**. It runs by itself for about 40 seconds; narrate as the steps light up:

   | Step | Mode | What to point at |
   |------|------|------------------|
   | 1 At the depot | Online | "Cameron gets WO-2026-0001. The repair plan is copied from the cloud database onto the tablet." |
   | 2 Highway | Limited | "One bar of signal: watch the chips slide to the **Edge**." |
   | 3 On site | Offline | "No signal at all. Lockout steps go to the **outbox**. The Cloud is greyed out." |
   | 4 Repair | Offline + sensors lost | "The gateway loses power, so the **tablet** runs the model from symptoms alone: 0 tokens, no network." |
   | 5 Close out | Offline | "Findings and a photo are queued. Nothing is lost." |
   | 6 Driving out | Limited | "First signal: safety and job updates sync first; the photo waits." |
   | 7 Back online | Online | "Everything is back in the cloud database, every step exactly once." |

3. If you're running short, use **Next step** and skip ahead instead of **Play all**.

### Optional · the AI manual agent

On the live page, click **Ask the manual agent (RAG)**. With an API key and Online, Claude searches the manuals and answers with cited steps (20–60 s). Then set **Offline** and ask again: the edge answers instantly from its own copy of the manuals, with no LLM. "Same question, the answer comes from wherever it can."

### 4:00–4:30 · The proof

1. Point at the **Live requests** totals: about 55 requests, with **about half running on the edge or device**, and tokens split across cloud, edge and device.
2. Click **Supervisor**, then **WO-2026-0001**: status **completed**. The activity feed shows the offline steps arriving after the fact.

### Optional, +1 minute · "Is this real?" (live demo)

1. Open http://127.0.0.1:8803/live.html: "These are four separate processes: cloud, edge, tablet, and a network in between that I can break."
2. Click **Run the repair story**. Point at the requests table: "Each row shows every place it tried, with the real milliseconds. Offline, the lockout steps go into the tablet's outbox; back online, they replay into the cloud database, exactly once."

### 4:30–5:00 · Close (spoken, or design deck slide 24)

"Today it's a simulation, with the same contracts, database and model we'd deploy. Next: real agents on these tools, a pilot with one depot, and we'll measure time to diagnose, first-time fix rate and return visits."

---

## If you're asked

| Question | Short answer | Where to show it |
|---|---|---|
| "What if the cloud AI goes down?" | Tick **Cloud AI outage**: language-model work moves to the edge; the trained model and the data keep working. | Mode bar → Events |
| "Is the diagnosis real?" | A trained model: 94.5% top-1 on simulated data it hadn't seen. Real accuracy needs our repair history. | Supervisor → W1 |
| "Where is the data?" | Each place lists its databases: the cloud repair DB, the edge telemetry buffer, the tablet's mission pack and outbox. | Where agents run |
| "Can the assistant answer offline?" | Set **Offline**, click **Ask**, try "How do I fix it?". The answer comes from the edge model, at zero cloud tokens. | Ask button |
