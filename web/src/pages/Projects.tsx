import { motion } from "framer-motion";
import { ClipboardList, FolderKanban, Plus, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAsk } from "../components/Ask";
import { Page } from "../components/Layout";
import { Badge, Dialog, Empty, ErrorNote, PageHeader, Spinner, spring } from "../components/ui";
import { api, useApi } from "../lib/api";
import { cn, dueLabel, SOURCE_LABEL, timeAgo } from "../lib/utils";

const STEP: Record<string, { label: string; tone: any; num: string }> = {
  done: { label: "Done", tone: "green", num: "bg-[#1A7431] text-white" },
  done_out_of_order: { label: "Done, out of order", tone: "orange", num: "bg-orange/[0.14] text-orange" },
  needs_confirmation: { label: "Needs your OK", tone: "blue", num: "bg-accent/10 text-accent-ink" },
  pending: { label: "Open", tone: "gray", num: "fill text-muted" },
  skipped: { label: "Skipped", tone: "gray", num: "fill text-muted" },
};

export function Projects() {
  const { data, error } = useApi<{ projects: any[] }>("/projects");
  const [creating, setCreating] = useState(false);
  const active = data?.projects.filter((p) => p.status === "active") ?? [];
  const done = data?.projects.filter((p) => p.status !== "active") ?? [];
  return (
    <Page>
      <PageHeader title="Projects" subtitle="Each project runs an SOP. Relay ticks steps off from email, calendar and tasks.">
        <button className="btn btn-primary" onClick={() => setCreating(true)}><Plus size={16} />Start from SOP</button>
      </PageHeader>
      {error && <ErrorNote message={error} />}
      {!data ? <div className="flex justify-center py-16"><Spinner /></div> : active.length === 0 ? (
        <Empty title="No active projects" icon={<FolderKanban size={20} />}>Start one from a published SOP.</Empty>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
          {active.map((p) => <ProjectCard key={p.id} p={p} />)}
        </div>
      )}
      {done.length > 0 && <>
        <h2 className="mt-4 text-[15px] font-semibold text-muted">Finished ({done.length})</h2>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4 opacity-80">{done.slice(0, 6).map((p) => <ProjectCard key={p.id} p={p} />)}</div>
      </>}
      <StartProject open={creating} onClose={() => setCreating(false)} />
    </Page>
  );
}

function ProjectCard({ p }: { p: any }) {
  const pct = p.total ? p.done / p.total : 0;
  return (
    <Link to={`/projects/${p.id}`} className="card flex items-center gap-4 p-4 transition hover:shadow-lift active:scale-[0.99]">
      <Ring pct={pct} label={`${p.done}/${p.total}`} size={56} />
      <div className="min-w-0">
        <p className="truncate text-[15px] font-semibold">{p.name}</p>
        <p className="text-[12.5px] text-muted">Started {timeAgo(p.started_at)}</p>
      </div>
    </Link>
  );
}

function Ring({ pct, label, size = 84 }: { pct: number; label: string; size?: number }) {
  const r = size / 2 - 7;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} role="img" aria-label={`${label} steps done`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(118,118,128,0.14)" strokeWidth={size > 60 ? 8 : 6} />
        <motion.circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1A7431" strokeWidth={size > 60 ? 8 : 6} strokeLinecap="round"
          strokeDasharray={c} initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - pct) }} transition={{ type: "spring", bounce: 0, duration: 0.8 }}
          transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-bold tabular-nums tracking-[-0.02em]" style={{ fontSize: size > 60 ? 19 : 14 }}>{label}</span>
    </div>
  );
}

export function Project() {
  const { id } = useParams();
  const { data: p, error, setData } = useApi<any>(`/projects/${id}`, 8000);
  const ask = useAsk();
  if (error) return <Page><ErrorNote message={error} /></Page>;
  if (!p) return <Page><div className="flex justify-center py-16"><Spinner /></div></Page>;
  const pending = p.steps.find((s: any) => s.status === "needs_confirmation");
  const confirm = async (spId: number, yes: boolean) => setData(await api(`/step-progress/${spId}/confirm`, { body: { yes } }));

  return (
    <Page>
      <header className="flex flex-wrap items-center gap-6">
        <Ring pct={p.steps.length ? p.done / p.steps.length : 0} label={`${p.done}/${p.steps.length}`} />
        <div className="flex min-w-[260px] flex-1 flex-col gap-1.5">
          <nav className="text-[13px] text-muted"><Link to="/projects">Projects</Link> / {p.team?.name}</nav>
          <h1 className="text-[30px] font-bold leading-tight tracking-[-0.024em]">{p.name}</h1>
          <div className="flex flex-wrap gap-1.5">
            {p.sop && <Link to={`/sops/${p.sop.id}`} className="chip hover:text-fg"><ClipboardList size={13} />{p.sop.title} · v{p.sop.version}</Link>}
            <span className="chip">Started {new Date(p.started_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span>
            {p.owner && <span className="chip">Owner · {p.owner.name}</span>}
          </div>
        </div>
        <button className="btn btn-primary" onClick={() => ask(`Where is ${p.name}?`)}><Sparkles size={15} />Ask about this</button>
      </header>

      {p.drift.map((d: any) => (
        <div key={d.id} className="flex flex-wrap items-center gap-3.5 rounded-2xl bg-purple/[0.12] px-[18px] py-3.5">
          <Sparkles size={20} className="shrink-0 text-purple" aria-hidden />
          <span className="min-w-[240px] flex-1 text-[14px]"><strong className="font-semibold">The SOP may be out of date.</strong> {d.text}</span>
          <Link className="btn btn-secondary" to={`/sops/${p.sop.id}`}>Review change</Link>
        </div>
      ))}

      <div className="flex flex-wrap items-start gap-6">
        <section className="card min-w-0 flex-[1_1_540px] overflow-hidden" aria-label="SOP steps">
          <div className="flex flex-wrap items-center gap-2.5 px-5 py-4">
            <h2 className="text-[16px] font-semibold">SOP vs what actually happened</h2>
            <span className="ml-auto text-[12.5px] text-muted">Matched automatically from email, calendar and tasks</span>
          </div>
          <ol>
            {p.steps.map((s: any) => {
              const st = STEP[s.status] ?? STEP.pending;
              return (
                <li key={s.step_progress_id} className={cn("grid grid-cols-[32px_1fr_auto] items-start gap-3.5 border-t border-line/[0.07] px-5 py-4 transition-colors", s.status === "needs_confirmation" && "bg-accent/[0.06]")}>
                  <span className={cn("flex h-8 w-8 items-center justify-center rounded-full text-[13px] font-semibold", st.num)}>{s.seq}</span>
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="text-[15px] font-semibold">{s.title}</span>
                    {s.evidence && <span className="text-[13.5px] text-fg2">{s.evidence}</span>}
                    <span className="mt-1 flex flex-wrap gap-1.5">
                      <span className="chip h-6 text-[12px]">{s.owner || "Unassigned"}</span>
                      <span className="chip h-6 text-[12px]">Done when: {s.evidence_type}</span>
                      {s.task_id && <Link to={`/tasks?task=${s.task_id}`} className="chip h-6 text-[12px] hover:text-fg">Task</Link>}
                    </span>
                  </div>
                  <span className="flex flex-col items-end gap-1">
                    <Badge tone={st.tone}>{st.label}</Badge>
                    {s.status === "pending" && s.due_at && <span className="text-[12px] text-muted">{dueLabel(s.due_at)}</span>}
                  </span>
                </li>
              );
            })}
          </ol>
        </section>
        <aside className="flex min-w-[280px] flex-[0_1_340px] flex-col gap-4">
          {pending && (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={spring} className="card flex flex-col gap-3 border-accent/35 px-5 py-[18px]">
              <span className="caption text-accent-ink">Relay isn't sure</span>
              <h2 className="text-[17px] font-semibold leading-snug">Does this complete step {pending.seq}, “{pending.title}”?</h2>
              <p className="rounded-xl px-3 py-2.5 text-[13.5px] fill">{pending.evidence}{pending.confidence ? ` · ${Math.round(pending.confidence * 100)}% match` : ""}</p>
              <div className="flex gap-2">
                <button className="btn btn-primary flex-1" onClick={() => confirm(pending.step_progress_id, true)}>Yes, it does</button>
                <button className="btn btn-secondary flex-1" onClick={() => confirm(pending.step_progress_id, false)}>No</button>
              </div>
              <span className="text-[12px] text-muted">Your answer teaches Relay how your team names things.</span>
            </motion.div>
          )}
          <div className="card px-5 pb-2.5 pt-4">
            <h2 className="mb-1.5 text-[15px] font-semibold">Recent activity</h2>
            {p.activity.length === 0 && <p className="py-3 text-[13.5px] text-muted">Nothing yet.</p>}
            {p.activity.map((a: any, n: number) => (
              <div key={n} className="flex flex-col gap-0.5 border-t border-line/[0.07] py-2 text-[13.5px] first:border-0">
                <span>{a.summary}</span><span className="text-[12px] text-muted">{timeAgo(a.at)} · {SOURCE_LABEL[a.source] ?? a.source}</span>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </Page>
  );
}

function StartProject({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data } = useApi<{ sops: any[] }>(open ? "/sops" : null);
  const [sopId, setSopId] = useState("");
  const [subject, setSubject] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const nav = useNavigate();
  const published = data?.sops.filter((s) => s.status === "published") ?? [];
  const sop = published.find((s) => String(s.id) === sopId);
  const submit = async () => {
    try {
      const p = await api("/projects", { body: { sop_id: Number(sopId), subject: subject || null, name: subject ? `${sop.title} — ${subject}` : sop.title } });
      onClose();
      nav(`/projects/${p.id}`);
    } catch (e: any) {
      setErr(e.message);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} title="Start a project">
      <form onSubmit={(e) => (e.preventDefault(), submit())} className="flex flex-col gap-4 p-6">
        <h2 className="text-[20px] font-semibold tracking-[-0.02em]">Start a project from an SOP</h2>
        <div><label className="label" htmlFor="sp-sop">SOP</label>
          <select id="sp-sop" className="input" value={sopId} onChange={(e) => setSopId(e.target.value)}>
            <option value="">Choose…</option>{published.map((s) => <option key={s.id} value={s.id}>{s.title} · v{s.version} ({s.team})</option>)}
          </select></div>
        <div><label className="label" htmlFor="sp-sub">Who or what is it about?</label>
          <input id="sp-sub" className="input" placeholder="e.g. Rahul Menon, Lumen Logistics" value={subject} onChange={(e) => setSubject(e.target.value)} /></div>
        {sop && <p className="text-[13px] text-muted">Creates {sop.steps.length} tasks, assigned to each step's owner team.</p>}
        {err && <ErrorNote message={err} />}
        <div className="flex justify-end gap-2"><button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!sopId}>Start project</button></div>
      </form>
    </Dialog>
  );
}
