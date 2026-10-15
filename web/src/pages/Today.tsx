import { AnimatePresence, motion } from "framer-motion";
import { Bell, BellOff, Check, ChevronDown, Clock, FileText, GitCommitHorizontal, GitPullRequest, Lightbulb, Mail, Play, RefreshCw, Sparkles, Square, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ConnectedTools } from "../components/Devices";
import { Page } from "../components/Layout";
import { Badge, ErrorNote, Spinner, spring } from "../components/ui";
import { api, useApi } from "../lib/api";
import { useSession } from "../lib/session";
import { cn, firstName, timeAgo } from "../lib/utils";

type Ctx = { kind: string; title: string; detail: string };
type Item = { rank: number; task_id: number; key: string; title: string; type: string; quadrant: string; quadrant_label: string; why: string;
  estimate_min: number; estimate_basis: string; focus_start: string | null; focus_end: string | null; context: Ctx[]; done: boolean };
type Ev = { id: number; title: string; start: string; end: string; kind: string; source: string; task_id: number | null };
type Day = { day: string; summary: string; focus_minutes: number; by_ai: boolean; items: Item[]; calendar: Ev[]; meeting_minutes: number; generated_at: string };
type Note = { id: number; kind: string; title: string; body: string; urgent: boolean; why: string; status: string; created_at: string; task_id: number | null };
type Question = { id: number; task_id: number; key: string; title: string; question: string; suggestion: string; asked_at: string };
type Inbox = { focus: { active: boolean; ends_at: string | null; title: string | null; task_id: number | null }; held: Note[]; delivered: Note[];
  stats: { held_today: number; let_through_today: number } };

const QUAD: Record<string, "red" | "blue" | "orange" | "gray"> = { do: "red", schedule: "blue", delegate: "orange", later: "gray" };
const CTX_ICON: Record<string, any> = { email: Mail, file: FileText, commit: GitCommitHorizontal, git: GitCommitHorizontal, pr: GitPullRequest,
  related: Lightbulb, claude: Sparkles, incident: Zap, meeting: Sparkles };

const hm = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
const dur = (m: number) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} m` : ""}` : `${m} m`);
function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export default function Today() {
  const { me } = useSession();
  const day = useApi<Day>("/me/day");
  const inbox = useApi<Inbox>("/me/notifications", 10000);
  const questions = useApi<{ questions: Question[] }>("/me/questions", 15000);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const act = async (key: string, fn: () => Promise<any>) => {
    setBusy(key);
    setErr(null);
    try {
      await fn();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  };
  const replan = () => act("plan", async () => day.setData(await api<Day>("/me/day/plan", { body: {} })));
  const startFocus = (task?: Item) => act(`focus-${task?.task_id ?? "any"}`, async () => {
    inbox.setData(await api<Inbox>("/me/focus", { body: { minutes: task?.estimate_min ?? 50, task_id: task?.task_id ?? null } }));
  });
  const endFocus = () => act("end", async () => inbox.setData(await api<Inbox>("/me/focus/end", { body: {} })));
  const markDone = (it: Item) => act(`done-${it.task_id}`, async () => {
    await api(`/tasks/${it.task_id}`, { method: "PATCH", body: { status: "done" } });
    day.setData((d) => d && { ...d, items: d.items.map((x) => (x.task_id === it.task_id ? { ...x, done: true } : x)) });
  });

  const d = day.data;
  const f = inbox.data?.focus;
  const dateLabel = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }).toUpperCase();

  return (
    <Page className="max-w-[1160px]">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <p className="text-[13px] font-semibold tracking-[0.02em] text-muted">{dateLabel}</p>
          <h1 className="text-[34px] font-bold leading-tight tracking-[-0.025em]">{greeting()}, {firstName(me?.user.name)}</h1>
          {d && (
            <p className="flex max-w-[640px] items-start gap-2 text-[17px] leading-snug text-fg2">
              {d.by_ai && <Sparkles size={17} className="mt-[3px] shrink-0 text-purple" aria-label="Planned by Relay" />}{d.summary}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {!f?.active && <button className="btn btn-primary" disabled={!!busy} onClick={() => startFocus(d?.items.find((i) => !i.done))}><Play size={15} />Start focus</button>}
          <button className="btn btn-secondary" disabled={!!busy} onClick={replan}>
            {busy === "plan" ? <Spinner className="h-4 w-4" /> : <RefreshCw size={15} />}Replan my day
          </button>
        </div>
      </header>

      {d && (
        <div className="flex flex-wrap gap-2">
          <span className="chip"><Check size={14} />{d.items.length} thing{d.items.length === 1 ? "" : "s"} today</span>
          <span className="chip bg-accent/10 text-accent-ink"><Clock size={14} />{dur(d.focus_minutes)} of focus booked</span>
          <span className="chip">{dur(d.meeting_minutes)} in meetings</span>
          <span className="chip">Planned {timeAgo(d.generated_at)}</span>
        </div>
      )}

      <AnimatePresence>
        {f?.active && (
          <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={spring}
            className="flex flex-wrap items-center gap-3 rounded-2xl bg-[#1D1D1F] px-5 py-3.5 text-white dark:bg-surface dark:text-fg">
            <BellOff size={20} aria-hidden />
            <span className="min-w-[220px] flex-1 text-[15px]"><strong className="font-semibold">In focus until {hm(f.ends_at!)}.</strong>{" "}
              {inbox.data!.held.length} notification{inbox.data!.held.length === 1 ? "" : "s"} held; only urgent ones come through.</span>
            <button className="btn h-9 bg-white/15 px-4 text-white hover:bg-white/25 dark:bg-[rgba(118,118,128,0.2)] dark:text-fg" onClick={endFocus} disabled={!!busy}>
              <Square size={13} fill="currentColor" />End focus
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {questions.data && questions.data.questions.length > 0 && (
        <section aria-label="Questions from Relay" className="flex flex-col gap-2.5">
          {questions.data.questions.map((q) => <QuestionCard key={q.id} q={q} onDone={questions.refresh} />)}
        </section>
      )}

      {(day.error || err) && <ErrorNote message={(day.error || err)!} />}
      {!d && !day.error && <div className="flex flex-col items-center gap-3 py-16 text-muted"><Spinner /><span className="text-[14px]">Relay is planning your day…</span></div>}

      {d && (
        <div className="flex flex-wrap items-start gap-6">
          <section aria-label="Top three" className="flex min-w-0 flex-[1_1_560px] flex-col gap-3">
            {d.items.length === 0 && (
              <div className="card flex flex-col items-center gap-2 px-6 py-12 text-center">
                <Check size={22} className="text-green" />
                <p className="text-[17px] font-semibold">Nothing assigned to you</p>
                <p className="max-w-sm text-[14px] text-muted">A good day to help a teammate or pick something up from the board.</p>
                <Link to="/tasks" className="btn btn-secondary mt-2">Open the board</Link>
              </div>
            )}
            {d.items.map((it, i) => <PlanCard key={it.task_id} it={it} i={i} busy={busy} focusActive={!!f?.active && f.task_id === it.task_id}
              onFocus={() => startFocus(it)} onDone={() => markDone(it)} />)}
          </section>
          <aside className="flex min-w-[280px] flex-[1_1_300px] flex-col gap-4 lg:max-w-[340px]">
            <ConnectedTools />
            <Timeline events={d.calendar} />
            {inbox.data && <InboxCard inbox={inbox.data} />}
          </aside>
        </div>
      )}
    </Page>
  );
}

function PlanCard({ it, i, busy, focusActive, onFocus, onDone }: { it: Item; i: number; busy: string | null; focusActive: boolean; onFocus: () => void; onDone: () => void }) {
  const [open, setOpen] = useState(i === 0);
  return (
    <motion.article initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: i * 0.06 }}
      className={cn("card overflow-hidden", it.done && "opacity-60")}>
      <div className="flex gap-4 px-5 pb-4 pt-[18px]">
        <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[16px] font-bold tabular-nums",
          it.done ? "bg-green/[0.14] text-green" : "fill text-fg")}>{it.done ? <Check size={17} strokeWidth={2.6} /> : it.rank}</span>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={QUAD[it.quadrant] ?? "gray"}>{it.quadrant_label}</Badge>
            <span className="text-[12.5px] text-muted">{it.key}</span>
          </div>
          <h2 className={cn("text-[18px] font-semibold leading-snug tracking-[-0.016em]", it.done && "line-through")}>{it.title}</h2>
          <p className="text-[14.5px] text-fg2">{it.why}</p>
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted">
            <span className="flex items-center gap-1.5"><Clock size={14} aria-hidden />About {dur(it.estimate_min)} · {it.estimate_basis}</span>
            <span>{it.focus_start ? `Focus booked ${hm(it.focus_start)}–${hm(it.focus_end!)}` : "No free slot left today"}</span>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-line/[0.07] px-5 py-3">
        {!it.done && (focusActive
          ? <span className="btn btn-done"><BellOff size={15} />Focusing on this</span>
          : <button className="btn btn-primary" disabled={!!busy} onClick={onFocus}><Play size={14} />Focus {dur(it.estimate_min)}</button>)}
        {!it.done && <button className="btn btn-secondary" disabled={!!busy} onClick={onDone}><Check size={15} />Done</button>}
        <Link className="btn btn-ghost" to={`/tasks?task=${it.task_id}`}>Open task</Link>
        {it.context.length > 0 && (
          <button className="btn btn-ghost ml-auto text-muted" aria-expanded={open} onClick={() => setOpen(!open)}>
            What you need · {it.context.length}<ChevronDown size={15} className={cn("transition-transform duration-300 ease-apple", open && "rotate-180")} />
          </button>
        )}
      </div>
      <AnimatePresence initial={false}>
        {open && it.context.length > 0 && (
          <motion.ul initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={spring}
            className="overflow-hidden border-t border-line/[0.07] bg-[rgba(118,118,128,0.04)]">
            {it.context.map((c, n) => {
              const Icon = CTX_ICON[c.kind] ?? FileText;
              return (
                <li key={n} className="flex gap-3 px-5 py-3 text-[14px] [&+&]:border-t [&+&]:border-line/[0.07]">
                  <Icon size={16} className="mt-0.5 shrink-0 text-muted" aria-hidden />
                  <span className="min-w-0"><span className="font-medium">{c.title}</span>{c.detail && <span className="block text-[13px] text-muted">{c.detail}</span>}</span>
                </li>
              );
            })}
          </motion.ul>
        )}
      </AnimatePresence>
    </motion.article>
  );
}

function Timeline({ events }: { events: Ev[] }) {
  const START = 9, END = 19, PX = 52;
  const [nowTick, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60000);
    return () => clearInterval(id);
  }, []);
  const pos = (iso: string | number) => {
    const t = new Date(iso);
    return ((t.getHours() + t.getMinutes() / 60) - START) * PX;
  };
  const nowY = pos(nowTick);
  const hours = useMemo(() => Array.from({ length: END - START + 1 }, (_, i) => START + i), []);
  // Side-by-side lanes for overlapping entries, per cluster of overlaps.
  const lanes = useMemo(() => {
    const sorted = [...events].sort((a, b) => +new Date(a.start) - +new Date(b.start));
    const out: { e: Ev; lane: number; of: number }[] = [];
    let cluster: { e: Ev; lane: number; of: number }[] = [], ends: number[] = [], clusterEnd = 0;
    const flush = () => { const n = Math.max(1, ends.length); cluster.forEach((c) => (c.of = n)); out.push(...cluster); cluster = []; ends = []; };
    for (const e of sorted) {
      const s = +new Date(e.start), en = +new Date(e.end);
      if (cluster.length && s >= clusterEnd) flush();
      let lane = ends.findIndex((x) => x <= s);
      if (lane === -1) { lane = ends.length; ends.push(en); } else ends[lane] = en;
      cluster.push({ e, lane, of: 1 });
      clusterEnd = Math.max(clusterEnd, en);
    }
    flush();
    return out;
  }, [events]);
  return (
    <div className="card px-4 pb-4 pt-4">
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="text-[15px] font-semibold">Your day</h2>
        <span className="flex items-center gap-3 text-[12px] text-muted">
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-accent" />Focus</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm fill-2" />Meetings</span>
        </span>
      </div>
      <div className="relative" style={{ height: (END - START) * PX }} role="img" aria-label={`${events.length} calendar entries today`}>
        {hours.map((h) => (
          <div key={h} className="absolute inset-x-0 flex items-start gap-2" style={{ top: (h - START) * PX }}>
            <span className="-mt-2 w-9 text-right text-[11px] tabular-nums text-muted">{String(h).padStart(2, "0")}:00</span>
            <span className="mt-px h-px flex-1 bg-line/[0.07]" />
          </div>
        ))}
        {lanes.map(({ e, lane, of }) => {
          const top = Math.max(0, pos(e.start)), h = Math.max(18, pos(e.end) - pos(e.start) - 2);
          const isFocus = e.kind === "focus";
          return (
            <motion.div key={e.id} initial={{ opacity: 0, x: 6 }} animate={{ opacity: 1, x: 0 }} transition={spring}
              className={cn("absolute overflow-hidden rounded-lg px-2.5 py-1 text-[12px] leading-tight",
                isFocus ? "bg-accent/[0.14] text-accent-ink ring-1 ring-inset ring-accent/30" : "fill-2 text-fg2")}
              style={{ top, height: h, left: `calc(44px + (100% - 48px) * ${lane / of})`, width: `calc((100% - 48px) / ${of} - 3px)` }}>
              <span className="font-semibold">{e.title}</span>
              {h > 30 && <span className="block opacity-80">{hm(e.start)}–{hm(e.end)}</span>}
            </motion.div>
          );
        })}
        {nowY > 0 && nowY < (END - START) * PX && (
          <div className="pointer-events-none absolute left-9 right-0 flex items-center" style={{ top: nowY }} aria-hidden>
            <span className="h-2 w-2 -translate-x-1 rounded-full bg-red" /><span className="h-px flex-1 bg-red" />
          </div>
        )}
      </div>
    </div>
  );
}

function InboxCard({ inbox }: { inbox: Inbox }) {
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center gap-2 px-[18px] pb-2 pt-4">
        <Bell size={16} aria-hidden /><h2 className="text-[15px] font-semibold">Notifications</h2>
        <span className="ml-auto text-[12px] text-muted">{inbox.stats.held_today} held today</span>
      </div>
      {inbox.held.length > 0 && (
        <div className="mx-3 mb-2 rounded-[14px] bg-accent/[0.08] px-3.5 py-3">
          <p className="flex items-center gap-1.5 text-[13px] font-semibold text-accent-ink"><BellOff size={14} />Held until your focus ends · {inbox.held.length}</p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {inbox.held.map((n) => <li key={n.id} className="text-[13.5px] text-fg2">{n.title}<span className="block text-[12px] text-muted">{n.why}</span></li>)}
          </ul>
        </div>
      )}
      <ul>
        {inbox.delivered.slice(0, 6).map((n) => (
          <li key={n.id} className="flex gap-2.5 border-t border-line/[0.07] px-[18px] py-2.5 text-[13.5px]">
            <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", n.urgent && n.why ? "bg-red" : n.status === "released" ? "bg-accent" : "fill-2")} />
            <span className="min-w-0 flex-1">
              <span className="font-medium">{n.title}</span>
              <span className="block text-[12px] text-muted">
                {n.urgent && n.why ? `Came through during focus: ${n.why}` : n.status === "released" ? "Held during focus, delivered after" : timeAgo(n.created_at)}
              </span>
            </span>
          </li>
        ))}
        {inbox.delivered.length === 0 && inbox.held.length === 0 && <li className="px-[18px] pb-4 text-[13.5px] text-muted">Nothing new.</li>}
      </ul>
    </div>
  );
}

function QuestionCard({ q, onDone }: { q: Question; onDone: () => void }) {
  const [text, setText] = useState(q.suggestion);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await api(`/tasks/${q.task_id}/outcome`, { body: { text } });
      onDone();
    } finally {
      setBusy(false);
    }
  };
  return (
    <motion.div layout initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={spring}
      className="card flex flex-col gap-3 border-accent/30 px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles size={16} className="text-purple" aria-hidden />
        <span className="caption text-accent-ink">Relay needs one answer</span>
        <span className="text-[12.5px] text-muted">{q.key}</span>
      </div>
      <p className="text-[17px] font-semibold leading-snug tracking-[-0.014em]">{q.question}</p>
      <label htmlFor={`q-${q.id}`} className="sr-only">Expected outcome</label>
      <textarea id={`q-${q.id}`} rows={2} className="input h-auto py-2.5 text-[15px]" value={text} onChange={(e) => setText(e.target.value)} />
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn btn-primary" disabled={busy || !text.trim()} onClick={save}>{text === q.suggestion ? "Use this" : "Save"}</button>
        <span className="text-[12.5px] text-muted">{text === q.suggestion ? "Suggested by Relay from your session. Edit it if it's off." : "Your manager sees this as the goal."}</span>
      </div>
    </motion.div>
  );
}
