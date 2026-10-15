import { AudioLines, BellOff, CalendarDays, Mail, Play, RotateCcw, Sunrise, Terminal, Unplug, Zap } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Page } from "../components/Layout";
import { DeviceRow, type Device } from "../components/Devices";
import { Avatar, Badge, ErrorNote, PageHeader, Segmented, Spinner, Switch } from "../components/ui";
import { api, useApi } from "../lib/api";
import { useSession } from "../lib/session";
import { timeAgo } from "../lib/utils";

type Tab = "teams" | "ownership" | "ai" | "connections" | "audit" | "demo";

export default function Admin() {
  const [tab, setTab] = useState<Tab>("teams");
  const { me } = useSession();
  return (
    <Page>
      <PageHeader title="Admin" subtitle={`${me?.org.name} · data stored in ${me?.org.region === "asia-south1" ? "Mumbai (asia-south1)" : me?.org.region}`}>
        <Segmented label="Admin sections" value={tab} onChange={setTab} options={[
          { value: "teams", label: "Teams" }, { value: "ownership", label: "Ownership & routing" },
          { value: "ai", label: "AI settings" }, { value: "connections", label: "Connections" }, { value: "audit", label: "Audit log" }, { value: "demo", label: "Demo" },
        ]} />
      </PageHeader>
      {tab === "teams" && <Teams />}
      {tab === "ownership" && <Ownership />}
      {tab === "ai" && <AiSettings />}
      {tab === "connections" && <Connections />}
      {tab === "audit" && <Audit />}
      {tab === "demo" && <Demo />}
    </Page>
  );
}

function Teams() {
  const { data, error, refresh } = useApi<{ teams: any[] }>("/teams");
  const [editing, setEditing] = useState<number | null>(null);
  const [handles, setHandles] = useState("");
  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner />;
  const save = async (id: number) => {
    await api(`/teams/${id}`, { method: "PATCH", body: { handles } });
    setEditing(null);
    refresh();
  };
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4">
      {data.teams.map((t) => (
        <article key={t.id} className="card flex flex-col gap-3 px-5 py-[18px]">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-[10px] text-[12px] font-bold text-white" style={{ background: t.color }}>{t.short}</span>
            <div className="flex flex-1 flex-col leading-tight"><h2 className="text-[16px] font-semibold">{t.name}</h2>
              <span className="text-[12.5px] text-muted">{t.members.length} member{t.members.length === 1 ? "" : "s"} · lead {t.lead?.name.split(" ")[0] ?? "none"}</span></div>
            <button className="btn btn-ghost h-[30px] px-2.5" onClick={() => (setEditing(t.id), setHandles(t.handles))}>Edit</button>
          </div>
          <div className="rounded-xl px-3 py-2.5 fill">
            <span className="caption mb-0.5 block text-[11.5px]">Handles</span>
            {editing === t.id ? (
              <div className="flex flex-col gap-2">
                <textarea className="input h-auto py-2" rows={2} value={handles} onChange={(e) => setHandles(e.target.value)} aria-label="What this team handles" />
                <div className="flex gap-1.5"><button className="btn btn-primary btn-sm" onClick={() => save(t.id)}>Save</button><button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button></div>
              </div>
            ) : <span className="text-[13.5px] leading-snug text-fg2">{t.handles}</span>}
          </div>
          <div className="flex items-center">
            {t.members.map((u: any) => <Avatar key={u.id} user={u} size={28} className="-ml-1.5 border-2 border-surface first:ml-0" />)}
            <span className="ml-auto text-[12.5px] text-muted">New work goes to {t.lead?.name.split(" ")[0] ?? "the team"}</span>
          </div>
        </article>
      ))}
    </div>
  );
}

function Ownership() {
  const { data, error, refresh } = useApi<{ resources: any[] }>("/resources");
  const { teams } = useSession();
  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner />;
  const set = async (id: number, body: any) => {
    await api(`/resources/${id}`, { method: "PATCH", body });
    refresh();
  };
  return (
    <div className="flex flex-col gap-4">
      <div className="card flex gap-3.5 px-5 py-4 text-[14px]">
        <Unplug size={20} className="mt-0.5 shrink-0 text-accent-ink" aria-hidden />
        <p><strong className="font-semibold">How routing works.</strong> <span className="text-fg2">When something breaks, Relay works out which part failed and sends the task to that part's owner. The business owner gets an FYI. If no owner fits, it picks the team whose description matches best, and learns from every reassignment.</span></p>
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full border-collapse text-[14px]">
          <thead><tr className="text-left text-[12px] font-semibold text-muted">
            {["Resource", "Kind", "Owner team", "Business owner"].map((h) => <th key={h} scope="col" className="border-b border-line/[0.07] px-[18px] py-3">{h}</th>)}
          </tr></thead>
          <tbody>
            {data.resources.map((r) => (
              <tr key={r.id} className="border-b border-line/[0.07] last:border-0">
                <td className="px-[18px] py-3 font-medium">{r.name}</td>
                <td className="px-[18px] py-3 text-muted">{r.kind.replace("_", " ")}</td>
                {(["owner_team_id", "business_team_id"] as const).map((f) => (
                  <td key={f} className="px-[18px] py-3">
                    <select aria-label={`${f === "owner_team_id" ? "Owner" : "Business owner"} of ${r.name}`} className="input h-8 w-auto" value={r[f] ?? ""} onChange={(e) => set(r.id, { [f]: Number(e.target.value) || null })}>
                      <option value="">—</option>{teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                    </select>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AiSettings() {
  const { teams, reload, me } = useSession();
  const [email, setEmail] = useState(true);
  const set = async (id: number, autonomy: string) => {
    await api(`/teams/${id}`, { method: "PATCH", body: { autonomy } });
    reload();
  };
  const desc: Record<string, string> = { suggest: "Suggests only", draft: "Prepares work for a person to approve", act: "Acts, then tells the team" };
  return (
    <div className="flex flex-col gap-4">
      <div className="card overflow-hidden">
        <div className="px-[18px] pb-3 pt-4"><h2 className="text-[16px] font-semibold">How much Relay does on its own</h2>
          <p className="text-[13.5px] text-muted">Per team. Relay never sends money, emails or merges code beyond the level you choose.</p></div>
        {teams.map((t) => (
          <div key={t.id} className="flex flex-wrap items-center gap-4 border-t border-line/[0.07] px-[18px] py-3.5">
            <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: t.color }} />
            <span className="flex min-w-[160px] flex-1 flex-col"><span className="text-[14.5px] font-semibold">{t.name}</span><span className="text-[12.5px] text-muted">{desc[t.autonomy ?? "draft"]}</span></span>
            <Segmented size="sm" label={`Autonomy for ${t.name}`} value={t.autonomy ?? "draft"} onChange={(v) => set(t.id, v)}
              options={[{ value: "suggest", label: "Suggest only" }, { value: "draft", label: "Draft for approval" }, { value: "act", label: "Act, then tell" }]} />
          </div>
        ))}
      </div>
      <div className="card overflow-hidden">
        <div className="px-[18px] pb-3 pt-4"><h2 className="text-[16px] font-semibold">Privacy and safety</h2></div>
        {[
          ["Remove secrets and personal data before the AI reads anything", "API keys, passwords, card, Aadhaar and PAN numbers. Always on.", true, true],
          ["Spot requests in my email", "Each person opts in for their own inbox.", email, false],
          ["Ask only shows what the person can already see", "Answers are filtered by team membership. Always on.", true, true],
        ].map(([title, sub, on, locked]) => (
          <div key={title as string} className="flex items-center gap-4 border-t border-line/[0.07] px-[18px] py-3.5">
            <span className="flex flex-1 flex-col"><span className="text-[14.5px] font-medium">{title}</span><span className="text-[12.5px] text-muted">{sub}</span></span>
            <Switch label={title as string} checked={on as boolean} disabled={locked as boolean}
              onChange={async (v) => { setEmail(v); await api("/me/preferences", { method: "PATCH", body: { email_capture: v } }); }} />
          </div>
        ))}
      </div>
      <p className="text-[12.5px] text-muted">Signed in as {me?.user.email}. On Vertex AI or a paid Gemini API plan, prompts aren't used to train Google's models; free-tier keys may be.</p>
    </div>
  );
}

function Audit() {
  const { data, error } = useApi<{ entries: any[] }>("/audit", 10000);
  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner />;
  return (
    <div className="card overflow-x-auto">
      <table className="w-full border-collapse text-[14px]">
        <thead><tr className="text-left text-[12px] font-semibold text-muted">
          {["When", "Who", "What", "Why", "Approved by"].map((h) => <th key={h} scope="col" className="border-b border-line/[0.07] px-[18px] py-3">{h}</th>)}
        </tr></thead>
        <tbody>
          {data.entries.map((a) => (
            <tr key={a.id} className="border-b border-line/[0.07] align-top last:border-0">
              <td className="whitespace-nowrap px-[18px] py-3 tabular-nums text-muted">{timeAgo(a.at)}</td>
              <td className="px-[18px] py-3">{a.actor ? (a.actor.kind === "agent" ? <Badge tone="purple">Relay</Badge> : a.actor.name) : <Badge tone="purple">Relay</Badge>}</td>
              <td className="px-[18px] py-3 font-medium">{a.action}</td>
              <td className="px-[18px] py-3 text-[13.5px] text-fg2">{a.reason}</td>
              <td className="px-[18px] py-3 text-[13.5px] text-fg2">{a.approved_by}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Demo() {
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const nav = useNavigate();
  const run = async (key: string, path: string, after?: (r: any) => string) => {
    setBusy(key);
    try {
      const r = await api(path, { body: {} });
      setLog((l) => [`${new Date().toLocaleTimeString()} · ${after ? after(r) : "done"}`, ...l]);
    } catch (e: any) {
      setLog((l) => [`${new Date().toLocaleTimeString()} · ${e.message}`, ...l]);
    } finally {
      setBusy(null);
    }
  };
  const items = [
    { key: "plans", icon: Sunrise, title: "Plan everyone's day", sub: "What the 07:00 job does: Gemini picks each person's top 3, estimates them and books focus time.",
      path: "/demo/plan-everyone", after: (r: any) => `${r.queued} plans queued`, go: "/" },
    { key: "focus", icon: BellOff, title: "Meera starts focusing, 5 pings arrive", sub: "Starts a 50-minute focus block for Meera and sends five notifications. Only the urgent one should get through.",
      path: "/demo/focus/meera@acme.test", after: (r: any) => `${r.held} held, ${r.delivered} let through. Sign in as Meera to see it.`, go: "/" },
    { key: "meeting", icon: AudioLines, title: "Process the sample meeting", sub: "A 64-second Data and Finance sync: Gemini finds decisions, creates tasks and hands work over.",
      path: "/demo/meeting/sample", after: () => "Processing. Watch it on Meetings.", go: "/meetings" },
    { key: "break", icon: Zap, title: "Break the pipeline", sub: "Renames raw.orders.amount (yesterday's refactor) and runs orders_daily. The on-call agent takes over.",
      path: "/demo/pipeline/break", after: (r: any) => (r.incident ? `${r.incident} opened. Watch On-call.` : `Run ${r.state.toLowerCase()}`), go: "/oncall" },
    { key: "email", icon: Mail, title: "Ananya emails Meera", sub: "An ad-hoc request arrives. Relay creates a task and finds last quarter's reply.", path: "/demo/signal/email",
      after: (r: any) => `Task ${r.result["meera@acme.test"]?.task ?? "—"} created`, go: "/tasks" },
    { key: "calendar", icon: CalendarDays, title: "Priya books the induction", sub: "A calendar invite ticks off step 4 of Rahul's onboarding SOP.", path: "/demo/signal/calendar",
      after: (r: any) => `SOP steps touched: ${r.result.sop_steps.map((s: any) => s.status).join(", ") || "none"}`, go: "/projects" },
    { key: "session", icon: Terminal, title: "Abhijit's Cursor session hits a blocker", sub: "What relay-agent sends: new work, blocked on finance.refunds access, no clear goal. Relay creates the task, flags the blocker to his lead and asks him for the expected outcome.",
      path: "/demo/signal/session", after: (r: any) => `${r.result.created ? "Created" : "Updated"} ${r.result.task}; blockers: ${r.result.blockers.length}; asked for outcome: ${r.result.asked_outcome ? "yes" : "no"}`, go: "/team" },
    { key: "claude", icon: Terminal, title: "Rohan finishes a Claude session", sub: "The session-end hook summarises the work into the matching task.", path: "/demo/signal/claude",
      after: (r: any) => `${r.result.created ? "Created" : "Updated"} ${r.result.task} (${r.result.matched})`, go: "/tasks" },
    { key: "feed", icon: RotateCcw, title: "Rebuild the feed", sub: "What the 08:00 job does every weekday.", path: "/feed/rebuild", after: (r: any) => `${r.created_or_updated} cards refreshed`, go: "/feed" },
    { key: "reset", icon: RotateCcw, title: "Reset the pipeline", sub: "Puts the column and model SQL back so you can break it again.", path: "/demo/pipeline/reset", after: () => "Pipeline reset" },
  ];
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
        {items.map((it) => (
          <div key={it.key} className="card flex flex-col gap-2.5 p-5">
            <span className="flex items-center gap-2 text-[15px] font-semibold"><it.icon size={18} aria-hidden />{it.title}</span>
            <p className="flex-1 text-[13.5px] text-fg2">{it.sub}</p>
            <div className="flex gap-2">
              <button className="btn btn-primary" disabled={!!busy} onClick={() => run(it.key, it.path, it.after)}>{busy === it.key ? <Spinner className="text-white" /> : <><Play size={14} />Run</>}</button>
              {it.go && <button className="btn btn-ghost" onClick={() => nav(it.go)}>Go there</button>}
            </div>
          </div>
        ))}
      </div>
      {log.length > 0 && <div className="card flex flex-col gap-1 p-4 font-mono text-[12.5px]" role="log">{log.map((l, i) => <span key={i}>{l}</span>)}</div>}
    </div>
  );
}

function Connections() {
  const { data, error } = useApi<{ devices: Device[] }>("/admin/devices", 30000);
  if (error) return <ErrorNote message={error} />;
  if (!data) return <Spinner />;
  const live = data.devices.filter((d) => d.online).length;
  return (
    <div data-tour="connections" className="flex flex-col gap-4">
      <p className="text-[14px] text-fg2">
        relay-agent runs on each person's laptop, reads their AI coding sessions locally and reports here every few minutes.
        {" "}{data.devices.length} laptop{data.devices.length === 1 ? "" : "s"} connected, {live} live now.
      </p>
      <div className="card overflow-hidden">
        {data.devices.length === 0 && <p className="px-5 py-6 text-[14px] text-muted">No laptops yet. Ask people to run <code className="font-mono">python3 agent/relay_agent.py status</code>.</p>}
        {data.devices.map((d) => <DeviceRow key={d.id} d={d} />)}
      </div>
    </div>
  );
}
