import { useEffect, useRef, useState } from "react";
import { api, getKey, setKey, State, TraceEntry, Vertical } from "./api";

const PHASES = ["VERIFY_ID", "RESOLVE_INTENT", "PROCESS_CASE", "POST_PROCESS"];
const FIELDS = ["full_name", "dob", "phone", "email", "id_last4"];

const summarize = (t: TraceEntry) => {
  const d = t.data;
  if (t.kind === "tool") return `${d.name} (${d.tier})`;
  if (t.kind === "transition") return `${d.frm} → ${d.to}  ·  ${d.predicate}`;
  if (t.kind === "memory") return `${d.event}${d.deferred ? " · deferred" : ""}${d.intent ? " · " + d.intent : ""}`;
  if (t.kind === "safety") return d.event + (d.reason ? " · " + d.reason : "") + (d.category ? " · " + d.category : "");
  if (t.kind === "validator") return `${d.name} ${d.ok === false ? "FLAG" : "ok"}${d.hard ? " (hard)" : ""}`;
  if (t.kind === "llm") return `${d.call} · ${d.model}${d.cassette ? " · cassette" : ""}${d.latency_ms ? " · " + d.latency_ms + " ms" : ""}`;
  if (t.kind === "directive") return `${d.style} · ask=${d.ask ?? "—"}${d.tone ? " · tone" : ""}`;
  if (t.kind === "perception") return [d.intent, d.scope, d.emotion, d.wants_human && "wants_human", d.done && "done"].filter(Boolean).join(" · ");
  return d.event ?? "";
};

export default function App() {
  const [sid, setSid] = useState<string | null>(() => sessionStorage.getItem("sop_sid"));
  const [state, setState] = useState<State | null>(null);
  const [mode, setMode] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [consent, setConsent] = useState("default");
  const [today, setToday] = useState("2026-03-01");
  const [key, setKeyState] = useState(getKey());
  const [tab, setTab] = useState<"state" | "trace" | "safety" | "outbox">("state");
  const [allTurns, setAllTurns] = useState(false);
  const [outbox, setOutbox] = useState<{ emails: any[]; credits: any[] }>({ emails: [], credits: [] });
  const [verticals, setVerticals] = useState<Vertical[]>([]);
  const [vertical, setVertical] = useState<string>(() => sessionStorage.getItem("sop_vertical") || "insurance_claims_v1");
  const [required, setRequired] = useState(3);
  const bottom = useRef<HTMLDivElement>(null);

  function apply(r: any) {
    setState(r.state); setMode(r.mode); setRequired(r.required_fields ?? 3);
    if (r.vertical) { setVertical(r.vertical); sessionStorage.setItem("sop_vertical", r.vertical); }
  }
  async function newSession(v = vertical) {
    const r = await api.create({ consent_scenario: consent, demo_today: today, vertical: v });
    sessionStorage.setItem("sop_sid", r.session_id);
    setSid(r.session_id); apply(r);
  }
  useEffect(() => {
    api.verticals().then((r) => setVerticals(r.verticals)).catch(() => {});
    if (sid) api.get(sid).then(apply).catch(() => newSession());
    else newSession();
  }, []);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [state?.history?.length]);
  useEffect(() => { if (tab === "outbox") api.outbox().then(setOutbox); }, [tab, state?.turn]);
  const scripts = verticals.find((v) => v.name === vertical)?.scripts ?? {};

  async function send(t = text) {
    if (!sid || !t.trim() || busy) return;
    setBusy(true); setText("");
    try { const r = await api.send(sid, t); setState(r.state); }
    catch (e: any) { alert(e.message); }
    finally { setBusy(false); }
  }

  const s = state;
  const trace = s?.trace ?? [];
  const shown = allTurns ? trace : trace.filter((t) => t.turn === s?.turn);
  const safety = trace.filter((t) => t.kind === "safety" || (t.kind === "validator" && t.data.ok === false));
  const hints = s ? Object.entries(s.intent.case_hints).filter(([, v]) => v) : [];
  const u = s?.usage;
  return (
    <div className="app">
      <header>
        <div><h1>SOP Agent</h1><span className="sub">SOP in the harness, language in the model</span></div>
        <div className="controls">
          <label>vertical <select value={vertical} onChange={(e) => newSession(e.target.value)}>{(verticals.length ? verticals : [{ name: vertical, domain: vertical, scripts: {} }]).map((v) => <option key={v.name} value={v.name}>{v.domain}</option>)}</select></label>
          <label>consent <select value={consent} onChange={(e) => setConsent(e.target.value)}><option>default</option><option>timeout</option></select></label>
          <label>today <input className="date" value={today} onChange={(e) => setToday(e.target.value)} /></label>
          <input placeholder="API key (optional, session only)" value={key} onChange={(e) => { setKeyState(e.target.value); setKey(e.target.value); }} />
          <button onClick={() => newSession()}>New session</button>
          <span className={`mode ${mode}`}>{mode}</span>
        </div>
      </header>
      <div className="stepper">
        {PHASES.map((p) => <span key={p} className={`step ${s?.phase === p ? "active" : ""} ${PHASES.indexOf(p) < PHASES.indexOf(s?.phase ?? "") ? "done" : ""}`}>{p}</span>)}
        {(s?.phase === "HANDOFF" || s?.phase === "CLOSED") && <span className="step terminal">{s.phase}</span>}
        {u && <span className="usage">{u.calls} calls · {u.input_tokens + u.output_tokens} tok · {u.latency_ms} ms</span>}
      </div>
      <main>
        <section className="chat">
          <div className="messages">
            {s?.history?.map((m, i) => <div key={i} className={`msg ${m.role}`}><span>{m.text}</span></div>)}
            <div ref={bottom} />
          </div>
          <div className="quick">{Object.entries(scripts).map(([k, v]) => <button key={k} onClick={() => send(v)} disabled={busy || s?.closed} title={v}>{k}</button>)}</div>
          <form onSubmit={(e) => { e.preventDefault(); send(); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder={s?.closed ? "Session closed — start a new one" : "Type as the caller…"} disabled={busy || s?.closed} autoFocus />
            <button disabled={busy || s?.closed}>{busy ? "…" : "Send"}</button>
          </form>
        </section>
        <aside className="inspector">
          <nav>{(["state", "trace", "safety", "outbox"] as const).map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}{t === "safety" && safety.length > 0 ? ` (${safety.length})` : ""}</button>)}</nav>
          {tab === "state" && s && (
            <div className="panel">
              <h3>Identity gate</h3>
              <ul className="fields">{FIELDS.map((f) => <li key={f} className={s.identity.verified_fields.includes(f) ? "ok" : ""}>{s.identity.verified_fields.includes(f) ? "✓" : "○"} {f}</li>)}</ul>
              <div>{s.verified_count}/{required} fields · access {s.identity.access_granted ? <b className="ok">granted</b> : "closed"} · mismatched turns {s.identity.mismatched_turns}{s.identity.locked && <b className="warn"> · LOCKED</b>}</div>
              <div>role {s.identity.caller_role ?? "—"}{s.identity.caller_role === "representative" && <> · rep {s.identity.rep_verified ? "listed ✓" : "not listed"} · consent <b>{s.post_process.consent.state}</b> ({s.post_process.consent.polls} polls, {s.post_process.consent.scenario})</>}</div>
              <h3>Memory (survives phase boundaries)</h3>
              <div>intent <b>{s.intent.intent ?? "—"}</b>{s.intent.intent_turn && <em> · captured turn {s.intent.intent_turn}{s.intent.intent_turn && s.phase === "VERIFY_ID" ? " · deferred" : ""}</em>}</div>
              <div>hints {hints.length ? hints.map(([k, v]) => <span key={k} className="chip">{k}: {String(v)}</span>) : "—"}{s.intent.hints_turn && <em> · turn {s.intent.hints_turn}</em>}</div>
              <div>case <b>{s.intent.resolved_case ?? "—"}</b>{s.intent.handled_cases.length > 0 && <> · earlier {s.intent.handled_cases.join(", ")}</>}{s.intent.no_claims && " · no claims on file"}</div>
              {s.intent.candidate_cases?.length > 0 && <ul className="cands">{s.intent.candidate_cases.map((c: any) => <li key={c.case_id}>{c.case_id} · {c.label} <em>score {c.score}</em></li>)}</ul>}
              {Object.keys(s.documents).length > 0 && <div>documents {Object.entries(s.documents).map(([k, v]) => <span key={k} className="chip">{k}: {String(v)}</span>)}</div>}
              <h3>Conversation control</h3>
              <div>emotion <b>{s.control.emotion}</b> · persuasion budget spent {s.control.persuasion_spent}/2 · scope strikes {s.control.scope_strikes} · pending <b>{s.control.pending ?? "—"}</b></div>
              <div>post-process decision <b>{s.post_process.decision ?? "—"}</b> {s.post_process.receipt && <span className="chip">{s.post_process.receipt}</span>}</div>
              {s.control.escalation_reason && <div className="warn">escalation: {s.control.escalation_reason}</div>}
            </div>
          )}
          {tab === "trace" && (
            <div className="panel">
              <label className="toggle"><input type="checkbox" checked={allTurns} onChange={(e) => setAllTurns(e.target.checked)} /> all turns</label>
              {shown.map((t, i) => <details key={i} open={t.kind === "transition" || t.kind === "safety"}><summary className={t.kind}>{allTurns && <span className="turn">t{t.turn}</span>}{t.kind} <span className="sum">{summarize(t)}</span></summary><pre>{JSON.stringify(t.data, null, 1)}</pre></details>)}
            </div>
          )}
          {tab === "safety" && <div className="panel">{safety.length === 0 ? <em>no safety events</em> : safety.map((t, i) => <details key={i}><summary className={t.kind}><span className="turn">t{t.turn}</span>{summarize(t)}</summary><pre>{JSON.stringify(t.data, null, 1)}</pre></details>)}</div>}
          {tab === "outbox" && <div className="panel">
            {outbox.emails.length === 0 && outbox.credits.length === 0 && <em>empty</em>}
            {outbox.emails.map((e, i) => <details key={"e" + i} open><summary>email to {e.to_masked}</summary><pre>{JSON.stringify(e.summary, null, 1)}</pre></details>)}
            {outbox.credits.map((c, i) => <details key={"c" + i} open><summary>provisional credit {c.reference} · ${c.amount} · {c.case_id}</summary><pre>{JSON.stringify(c, null, 1)}</pre></details>)}
          </div>}
        </aside>
      </main>
    </div>
  );
}
