import { motion } from "framer-motion";
import { AudioLines, Ban, Bot, Check, GitCommitHorizontal, Mail, MessageSquareText, Plus, Sparkles, Target, Terminal, CalendarDays, ClipboardList, Zap, PenLine } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAsk } from "../components/Ask";
import { Page } from "../components/Layout";
import { Avatar, Badge, Dialog, ErrorNote, PageHeader, Segmented, Sheet, Spinner, spring, TeamDot } from "../components/ui";
import { api, useApi } from "../lib/api";
import { useSession } from "../lib/session";
import { cn, dueLabel, SOURCE_LABEL, timeAgo } from "../lib/utils";

const COLUMNS = [
  { key: "todo", label: "To do", dot: "rgb(var(--muted))" },
  { key: "doing", label: "In progress", dot: "#0071E3" },
  { key: "review", label: "In review", dot: "#C46A00" },
  { key: "done", label: "Done", dot: "#1A7431" },
];
const TYPE_BADGE: Record<string, [string, any]> = {
  incident: ["Failure", "red"], review: ["Review", "blue"], request: ["Email request", "orange"], sop_step: ["SOP step", "green"],
};
const SOURCE_ICON: Record<string, any> = { cursor: Terminal, codex: Terminal, antigravity: Terminal, meeting: AudioLines, claude: Terminal, git: GitCommitHorizontal, email: Mail, calendar: CalendarDays, oncall: Bot, sop: ClipboardList, manual: PenLine, kestra: Zap };

export default function Tasks() {
  const [params, setParams] = useSearchParams();
  const team = params.get("team");
  const selected = params.get("task");
  const [mine, setMine] = useState<"all" | "mine">("all");
  const [creating, setCreating] = useState(false);
  const query = `/tasks?${new URLSearchParams({ ...(team ? { team_id: team } : {}), ...(mine === "mine" ? { mine: "true" } : {}) })}`;
  const { data, error, loading, refresh } = useApi<{ tasks: any[]; auto_written_pct: number }>(query, 15000);
  const { teams } = useSession();
  const teamName = teams.find((t) => String(t.id) === team)?.name;

  const byCol = useMemo(() => {
    const out: Record<string, any[]> = { todo: [], doing: [], review: [], done: [] };
    data?.tasks.forEach((t) => out[t.status]?.push(t));
    out.done = out.done.slice(0, 12);
    return out;
  }, [data]);

  const open = (id: number | null) => {
    const p = new URLSearchParams(params);
    if (id) p.set("task", String(id));
    else p.delete("task");
    setParams(p, { replace: true });
  };

  return (
    <div className="flex min-h-screen">
      <Page className="min-w-0 max-w-none flex-1">
        <PageHeader title={teamName ?? "Tasks"} subtitle={data ? `${data.tasks.length} tasks · ${data.auto_written_pct}% of descriptions written by Relay` : " "}>
          <Segmented label="Whose tasks" value={mine} onChange={setMine} options={[{ value: "all", label: "Everyone" }, { value: "mine", label: "Mine" }]} />
          <button className="btn btn-primary" onClick={() => setCreating(true)}><Plus size={16} />New task</button>
        </PageHeader>
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={() => setParams(new URLSearchParams())} className={cn("chip", !team && "bg-accent/10 text-accent-ink")}>All teams</button>
          {teams.map((t) => (
            <button key={t.id} onClick={() => setParams(new URLSearchParams({ team: String(t.id) }))} className={cn("chip", String(t.id) === team && "bg-accent/10 text-accent-ink")}>
              <TeamDot color={t.color} />{t.name}
            </button>
          ))}
        </div>
        {error && <ErrorNote message={error} />}
        {loading && !data ? <div className="flex justify-center py-16"><Spinner /></div> : (
          <div className="flex items-start gap-4 overflow-x-auto pb-2">
            {COLUMNS.map((c) => (
              <section key={c.key} aria-label={c.label} className="flex min-w-[250px] flex-[1_0_250px] flex-col gap-2.5">
                <div className="flex items-center gap-2 px-1">
                  <span className="h-2 w-2 rounded-full" style={{ background: c.dot }} />
                  <h2 className="text-[13.5px] font-semibold">{c.label}</h2>
                  <span className="text-[13px] text-muted">{byCol[c.key].length}</span>
                </div>
                {byCol[c.key].map((t) => <TaskCard key={t.id} t={t} selected={String(t.id) === selected} onClick={() => open(t.id)} />)}
              </section>
            ))}
          </div>
        )}
      </Page>
      <Sheet open={!!selected} onClose={() => open(null)} title="Task details">
        {selected && <TaskPanel id={Number(selected)} onChanged={refresh} />}
      </Sheet>
      <NewTask open={creating} onClose={() => setCreating(false)} onCreated={(id) => { refresh(); open(id); }} />
    </div>
  );
}

function TaskCard({ t, selected, onClick }: { t: any; selected: boolean; onClick: () => void }) {
  const badge = TYPE_BADGE[t.type];
  const Icon = SOURCE_ICON[t.last_update?.source] ?? Sparkles;
  return (
    <motion.button layout transition={spring} onClick={onClick} aria-pressed={selected}
      className={cn("flex w-full flex-col gap-2 rounded-[14px] border bg-surface p-3.5 text-left shadow-card transition-[box-shadow,transform,border-color] duration-200 ease-apple hover:-translate-y-px hover:shadow-lift active:scale-[0.98]",
        selected ? "border-accent ring-[3px] ring-accent/20" : "border-line/[0.07]")}>
      <span className="flex items-center gap-1.5 text-[12px] font-medium text-muted">
        <TeamDot color={t.team?.color} />{t.team?.name ?? "No team"}<span className="ml-auto">{t.key}</span>
      </span>
      <span className="text-[14.5px] font-semibold leading-snug tracking-[-0.012em]">{t.title}</span>
      {(badge || t.due_at || t.description_by_ai || t.blockers?.length > 0) && (
        <span className="flex flex-wrap gap-1">
          {t.blockers?.length > 0 && <Badge tone="red"><Ban size={11} />Blocked</Badge>}
          {badge && <Badge tone={badge[1]}>{badge[0]}</Badge>}
          {t.created_by?.kind === "agent" && <Badge tone="purple">Created by AI</Badge>}
          {t.due_at && t.status !== "done" && <Badge tone={new Date(t.due_at) < new Date() ? "orange" : "gray"}>{dueLabel(t.due_at)}</Badge>}
        </span>
      )}
      <span className="flex items-center gap-2 text-[12px] text-muted">
        <Avatar user={t.assignee} />
        {t.last_update && <><Icon size={13} aria-hidden /><span className="truncate">{SOURCE_LABEL[t.last_update.source] ?? t.last_update.source} · {timeAgo(t.last_update.at)}</span></>}
      </span>
    </motion.button>
  );
}

function TaskPanel({ id, onChanged }: { id: number; onChanged: () => void }) {
  const { data: t, error, refresh, setData } = useApi<any>(`/tasks/${id}`, 10000);
  const { users } = useSession();
  const [comment, setComment] = useState("");
  const ask = useAsk();

  const patch = async (body: any) => {
    setData(await api(`/tasks/${id}`, { method: "PATCH", body }));
    onChanged();
  };
  const send = async () => {
    if (!comment.trim()) return;
    setData(await api(`/tasks/${id}/comments`, { body: { text: comment } }));
    setComment("");
  };

  if (error) return <div className="p-6"><ErrorNote message={error} /></div>;
  if (!t) return <div className="flex justify-center p-10"><Spinner /></div>;
  const sources = new Set(t.timeline.filter((e: any) => e.source !== "manual").map((e: any) => e.source)).size;

  return (
    <>
      <div className="flex flex-col gap-2.5 border-b border-line/[0.07] px-6 pb-4 pt-5">
        <span className="flex items-center gap-2 pr-10 text-[12.5px] text-muted"><TeamDot color={t.team?.color} />{t.team?.name} · {t.key}</span>
        <h2 className="text-[22px] font-bold leading-tight tracking-[-0.02em]">{t.title}</h2>
        <div className="flex flex-wrap gap-1">
          {TYPE_BADGE[t.type] && <Badge tone={TYPE_BADGE[t.type][1]}>{TYPE_BADGE[t.type][0]}</Badge>}
          {t.created_by?.kind === "agent" && <Badge tone="purple">Created by AI</Badge>}
          {t.priority === "high" && <Badge tone="red">High priority</Badge>}
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-6 py-4">
        <dl className="flex flex-col">
          <Field label="Status">
            <Segmented size="sm" label="Status" value={t.status} onChange={(v) => patch({ status: v })}
              options={COLUMNS.map((c) => ({ value: c.key, label: c.key === "doing" ? "Doing" : c.key === "review" ? "Review" : c.label }))} />
          </Field>
          <Field label="Assignee">
            <Avatar user={t.assignee} />
            <select aria-label="Assignee" className="min-w-0 flex-1 bg-transparent text-[13.5px] outline-none" value={t.assignee?.id ?? ""} onChange={(e) => patch({ assignee_id: Number(e.target.value) || null })}>
              <option value="">Nobody</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </Field>
          {t.due_at && <Field label="Due">{dueLabel(t.due_at)}</Field>}
          <Field label="Created by">{t.created_by ? t.created_by.name : "Relay, from email"}</Field>
          {t.project_id && <Field label="Project"><Link className="text-accent-ink" to={`/projects/${t.project_id}`}>Open project</Link></Field>}
        </dl>
        <section className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <h3 className="caption">Description</h3>
            {t.description_by_ai && <Badge tone="purple"><Sparkles size={11} fill="currentColor" />Written by Relay</Badge>}
          </div>
          <p className="whitespace-pre-line text-[14.5px] leading-relaxed text-fg2">{t.description || "No description yet. Relay fills this in from the work it sees."}</p>
          {t.description_by_ai && <p className="text-[12.5px] text-muted">From {sources || 1} source{sources === 1 ? "" : "s"} · updated {timeAgo(t.updated_at)}</p>}
        </section>
        <Outcome t={t} onSaved={setData} />
        {t.blockers.length > 0 && (
          <section className="flex flex-col gap-2">
            <h3 className="caption text-red">Blocked</h3>
            {t.blockers.map((b: any) => (
              <div key={b.id} className="flex items-start gap-3 rounded-xl bg-red/[0.07] px-3.5 py-3">
                <Ban size={16} className="mt-0.5 shrink-0 text-red" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] leading-snug">{b.text}</p>
                  <p className="mt-0.5 text-[12px] text-muted">{b.waiting_on ? `Waiting on ${b.waiting_on} · ` : ""}from {SOURCE_LABEL[b.source] ?? b.source} · {timeAgo(b.at)}</p>
                </div>
                <button className="btn btn-secondary btn-sm" onClick={async () => setData(await api(`/tasks/${id}/blockers/${b.id}/resolve`, { body: {} }))}>
                  <Check size={13} />Resolved
                </button>
              </div>
            ))}
          </section>
        )}
        {(t.links?.length > 0 || t.children?.length > 0) && (
          <section className="flex flex-col gap-2">
            <h3 className="caption">Linked</h3>
            <div className="flex flex-wrap gap-1.5">
              {t.links.map((l: any, i: number) => l.url
                ? <a key={i} className="chip hover:text-fg" href={l.url} target="_blank" rel="noreferrer">{l.label}</a>
                : <span key={i} className="chip">{l.label}</span>)}
              {t.children.map((c: any) => <Link key={c.id} className="chip hover:text-fg" to={`/tasks?task=${c.id}`}>{c.key} · {c.title}</Link>)}
            </div>
          </section>
        )}
        <section className="flex flex-col gap-2.5">
          <h3 className="caption">Timeline</h3>
          <ol className="flex flex-col">
            {t.timeline.map((e: any, i: number) => {
              const Icon = SOURCE_ICON[e.source] ?? PenLine;
              return (
                <li key={e.id} className="relative grid grid-cols-[28px_1fr] gap-2.5 pb-4">
                  {i < t.timeline.length - 1 && <span className="absolute bottom-0 left-[13.5px] top-[30px] w-px bg-line/[0.12]" />}
                  {e.author ? <Avatar user={e.author} size={28} /> : <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#1D1D1F] text-white"><Icon size={14} /></span>}
                  <div className="flex flex-col gap-0.5 pt-0.5">
                    <span className="text-[13.5px] leading-snug"><strong className="font-semibold">{e.author?.name.split(" ")[0] ?? "Relay"}</strong> {e.summary}</span>
                    <span className="flex items-center gap-1 text-[12px] text-muted"><Icon size={12} aria-hidden />{SOURCE_LABEL[e.source] ?? e.source} · {timeAgo(e.at)}</span>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      </div>
      <div className="flex flex-col gap-2 border-t border-line/[0.07] px-6 pb-5 pt-3.5">
        <div className="flex gap-2">
          <label htmlFor="comment" className="sr-only">Comment</label>
          <input id="comment" className="input" placeholder="Add an update…" value={comment} onChange={(e) => setComment(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} />
          <button className="btn btn-secondary" onClick={send}><MessageSquareText size={15} />Post</button>
        </div>
        <div className="flex gap-2">
          {t.status !== "done" && <button className="btn btn-primary" onClick={() => patch({ status: "done" })}>Mark done</button>}
          <button className="btn btn-ghost ml-auto" onClick={() => ask(`What's the history of ${t.key} ${t.title}?`)}>Ask about this</button>
          <button className="btn btn-ghost text-muted" onClick={refresh}>Refresh</button>
        </div>
      </div>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid min-h-9 grid-cols-[100px_1fr] items-center gap-2 text-[13.5px]">
      <dt className="text-muted">{label}</dt>
      <dd className="flex min-w-0 items-center gap-2">{children}</dd>
    </div>
  );
}

function NewTask({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: number) => void }) {
  const { teams, users } = useSession();
  const [form, setForm] = useState({ title: "", description: "", team_id: "", assignee_id: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!form.title.trim()) return;
    setBusy(true);
    try {
      const t = await api("/tasks", { body: { title: form.title, description: form.description, team_id: Number(form.team_id) || null, assignee_id: Number(form.assignee_id) || null } });
      setForm({ title: "", description: "", team_id: "", assignee_id: "" });
      onClose();
      onCreated(t.id);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} title="New task">
      <form onSubmit={(e) => (e.preventDefault(), submit())} className="flex flex-col gap-4 p-6">
        <h2 className="text-[20px] font-semibold tracking-[-0.02em]">New task</h2>
        <div><label className="label" htmlFor="nt-title">Title</label><input id="nt-title" autoFocus className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
        <div><label className="label" htmlFor="nt-desc">Description</label>
          <textarea id="nt-desc" rows={3} className="input h-auto py-2" placeholder="Optional — Relay will keep it up to date" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label" htmlFor="nt-team">Team</label>
            <select id="nt-team" className="input" value={form.team_id} onChange={(e) => setForm({ ...form, team_id: e.target.value })}>
              <option value="">My team</option>{teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select></div>
          <div><label className="label" htmlFor="nt-who">Assignee</label>
            <select id="nt-who" className="input" value={form.assignee_id} onChange={(e) => setForm({ ...form, assignee_id: e.target.value })}>
              <option value="">Team lead</option>{users.filter((u) => u.kind === "human").map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select></div>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !form.title.trim()}>Create task</button>
        </div>
      </form>
    </Dialog>
  );
}

function Outcome({ t, onSaved }: { t: any; onSaved: (d: any) => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(t.expected_outcome ?? "");
  const save = async () => {
    if (!text.trim()) return;
    onSaved(await api(`/tasks/${t.id}/outcome`, { body: { text } }));
    setEditing(false);
  };
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <h3 className="caption">Expected outcome</h3>
        {t.outcome_by_ai && <Badge tone="purple"><Sparkles size={11} fill="currentColor" />From the session</Badge>}
        {!editing && <button className="btn btn-ghost btn-sm ml-auto" onClick={() => (setText(t.expected_outcome ?? ""), setEditing(true))}>{t.expected_outcome ? "Edit" : "Add"}</button>}
      </div>
      {editing ? (
        <div className="flex flex-col gap-2">
          <label htmlFor="outcome" className="sr-only">Expected outcome</label>
          <textarea id="outcome" rows={2} className="input h-auto py-2" placeholder="What does done look like?" value={text} onChange={(e) => setText(e.target.value)} autoFocus />
          <div className="flex gap-2"><button className="btn btn-primary btn-sm" onClick={save}>Save</button><button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button></div>
        </div>
      ) : t.expected_outcome ? (
        <p className="flex items-start gap-2 text-[14.5px] leading-relaxed text-fg2"><Target size={16} className="mt-[3px] shrink-0 text-accent-ink" aria-hidden />{t.expected_outcome}</p>
      ) : (
        <p className="text-[14px] text-muted">Not set yet. Relay asks the assignee once, when the goal isn't clear from their work.</p>
      )}
    </section>
  );
}
