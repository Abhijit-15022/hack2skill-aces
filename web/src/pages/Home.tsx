import { AnimatePresence, motion } from "framer-motion";
import { Check, Clock, Eye, Lightbulb, Sparkles, Star, TrendingUp, UserRound, Zap } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAsk } from "../components/Ask";
import { Page } from "../components/Layout";
import { Dialog, ErrorNote, Segmented, Spinner, spring, TeamDot } from "../components/ui";
import { api, useApi } from "../lib/api";
import { useSession } from "../lib/session";
import { cn, dueLabel, firstName, timeAgo } from "../lib/utils";

type Card = {
  id: number; kind: string; title: string; body: string; team: string | null; created_at: string; sources: string[];
  actions: { type: string; user_id?: number; task_id?: number; incident_id?: number; step_progress_id?: number }[];
  data: { per_day?: number[] }; task_id: number | null; incident_id: number | null; project_id: number | null;
  kudos: number; kudos_by_me: boolean; nudged_by_me: boolean;
};
type Story = { team_id: number; name: string; short: string; color: string; health: "red" | "amber" | "green"; items: Card[] };
type Feed = { cards: Card[]; stories: Story[]; summary: { total: number; needs_you: number; handled: number } };

const KIND: Record<string, { label: string; tone: string; icon: typeof Zap }> = {
  needs: { label: "Needs you", tone: "bg-accent/10 text-accent-ink", icon: UserRound },
  incident: { label: "Failure", tone: "bg-red/10 text-red", icon: Zap },
  stuck: { label: "Stuck", tone: "bg-orange/[0.14] text-orange", icon: Clock },
  win: { label: "Shipped", tone: "bg-green/[0.14] text-green", icon: Check },
  decision: { label: "Decision", tone: "bg-purple/[0.12] text-purple", icon: Lightbulb },
  trend: { label: "Trend", tone: "bg-teal/[0.14] text-teal", icon: TrendingUp },
  invisible: { label: "Work nobody saw", tone: "fill text-fg2", icon: Eye },
};
const RING = { red: "#D70015", amber: "#E08A00", green: "#28A745" };

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export default function Home() {
  const { me, users } = useSession();
  const [filter, setFilter] = useState<"all" | "needs" | "failures" | "wins">("all");
  const { data, error, loading, refresh, setData } = useApi<Feed>(`/feed${filter === "all" ? "" : `?filter=${filter}`}`, 20000);
  const tasks = useApi<{ tasks: any[]; auto_written_pct: number }>("/tasks");
  const [story, setStory] = useState<Story | null>(null);
  const ask = useAsk();
  const nav = useNavigate();

  const react = async (card: Card, kind: "kudos" | "nudge") => {
    const r = await api<{ active: boolean }>(`/feed/${card.id}/react`, { body: { kind } });
    setData((d) => d && {
      ...d,
      cards: d.cards.map((c) => c.id !== card.id ? c : kind === "kudos"
        ? { ...c, kudos_by_me: r.active, kudos: c.kudos + (r.active ? 1 : -1) }
        : { ...c, nudged_by_me: true }),
    });
  };

  const confirmStep = async (card: Card, spId: number, yes: boolean) => {
    await api(`/step-progress/${spId}/confirm`, { body: { yes } });
    setData((d) => d && { ...d, cards: d.cards.filter((c) => c.id !== card.id) });
  };

  const stats = useMemo(() => {
    const t = tasks.data?.tasks ?? [];
    const dayAgo = Date.now() - 86400000;
    return {
      doing: t.filter((x) => x.status === "doing" || x.status === "review").length,
      closed: t.filter((x) => x.closed_at && new Date(x.closed_at).getTime() > dayAgo).length,
      due: t.filter((x) => x.due_at && x.status !== "done").sort((a, b) => +new Date(a.due_at) - +new Date(b.due_at)).slice(0, 3),
    };
  }, [tasks.data]);

  const userName = (id?: number) => firstName(users.find((u) => u.id === id)?.name) || "them";
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }).toUpperCase();

  return (
    <Page className="max-w-[1120px]">
      <div className="flex flex-wrap items-start justify-center gap-9">
        <section aria-label="Feed" className="flex min-w-0 max-w-[680px] flex-[1_1_520px] flex-col gap-5">
          <header>
            <p className="text-[13px] font-semibold tracking-[0.02em] text-muted">{today}</p>
            <h1 className="text-[34px] font-bold leading-tight tracking-[-0.025em]">{greeting()}, {firstName(me?.user.name)}</h1>
          </header>

          {data && data.stories.length > 0 && (
            <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-2 pt-1" role="list" aria-label="Team stories">
              {data.stories.map((s) => (
                <button key={s.team_id} role="listitem" onClick={() => setStory(s)} aria-label={`${s.name}: ${s.health}`}
                  className="flex w-[76px] shrink-0 flex-col items-center gap-2 text-fg2 transition-transform duration-150 ease-apple active:scale-95">
                  <span className="flex h-16 w-16 rounded-full p-[3px]" style={{ background: RING[s.health] }}>
                    <span className="flex flex-1 rounded-full bg-bg p-[3px]">
                      <span className="flex flex-1 items-center justify-center rounded-full text-[15px] font-semibold text-white" style={{ background: s.color }}>{s.short}</span>
                    </span>
                  </span>
                  <span className="text-center text-[12px] font-medium leading-tight">{s.name}</span>
                </button>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <Segmented label="Filter feed" value={filter} onChange={setFilter} options={[
              { value: "all", label: "For you" },
              { value: "needs", label: `Needs you${data && filter === "all" ? ` · ${data.summary.needs_you}` : ""}` },
              { value: "failures", label: "Failures" },
              { value: "wins", label: "Wins" },
            ]} />
            <span className="text-[13px] text-muted">{data ? `${data.cards.length} update${data.cards.length === 1 ? "" : "s"}` : ""}</span>
          </div>

          {error && <ErrorNote message={error} />}
          {loading && !data && <div className="flex justify-center py-10"><Spinner /></div>}

          <AnimatePresence initial={false}>
            {data?.cards.map((c, i) => {
              const k = KIND[c.kind] ?? KIND.needs;
              const Icon = k.icon;
              const nudge = c.actions.find((a) => a.type === "nudge");
              const confirm = c.actions.find((a) => a.type === "confirm_step");
              return (
                <motion.article key={c.id} layout initial={{ opacity: 0, y: 8, scale: 0.99 }} animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.98 }} transition={{ ...spring, delay: Math.min(i, 8) * 0.05 }} className="card px-5 pb-4 pt-[18px]">
                  <div className="mb-2.5 flex items-center gap-2.5">
                    <span className={cn("inline-flex h-6 items-center gap-1.5 rounded-full pl-[7px] pr-[9px] text-[12.5px] font-semibold", k.tone)}>
                      <Icon size={14} strokeWidth={2.2} aria-hidden />{k.label}
                    </span>
                    {c.team && <span className="text-[12.5px] text-muted">{c.team}</span>}
                    <span className="ml-auto text-[12.5px] text-muted">{timeAgo(c.created_at)}</span>
                  </div>
                  <h2 className="text-[17px] font-semibold leading-snug tracking-[-0.015em]">{c.title}</h2>
                  <p className="mt-1 whitespace-pre-line text-[14.5px] leading-normal text-fg2">{c.body}</p>
                  {c.kind === "trend" && c.data.per_day && <Bars values={c.data.per_day} />}
                  {c.sources.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">{c.sources.filter(Boolean).map((s) => <span key={s} className="chip">{s}</span>)}</div>
                  )}
                  <div className="mt-3.5 flex flex-wrap gap-2 border-t border-line/[0.07] pt-3">
                    {confirm && <>
                      <button className="btn btn-primary" onClick={() => confirmStep(c, confirm.step_progress_id!, true)}>Yes, it's done</button>
                      <button className="btn btn-secondary" onClick={() => confirmStep(c, confirm.step_progress_id!, false)}>No</button>
                    </>}
                    {nudge && (
                      <button className={cn("btn", c.nudged_by_me ? "btn-done" : "btn-primary")} onClick={() => !c.nudged_by_me && react(c, "nudge")}>
                        {c.nudged_by_me ? <><Check size={15} />Nudged</> : `Nudge ${userName(nudge.user_id)}`}
                      </button>
                    )}
                    {c.incident_id && <Link className={cn("btn", nudge ? "btn-secondary" : "btn-primary")} to={`/oncall/${c.incident_id}`}>View investigation</Link>}
                    {["win", "invisible"].includes(c.kind) && (
                      <button className={cn("btn", c.kudos_by_me ? "btn-warm" : "btn-secondary")} aria-pressed={c.kudos_by_me} onClick={() => react(c, "kudos")}>
                        <Star size={15} fill={c.kudos_by_me ? "currentColor" : "none"} aria-hidden />Kudos{c.kudos ? ` · ${c.kudos}` : ""}
                      </button>
                    )}
                    {c.project_id && <Link className="btn btn-secondary" to={`/projects/${c.project_id}`}>Open project</Link>}
                    {c.task_id && !c.incident_id && <button className="btn btn-secondary" onClick={() => nav(`/tasks?task=${c.task_id}`)}>Open task</button>}
                    {(c.kind === "decision" || c.kind === "incident") && (
                      <button className="btn btn-ghost" onClick={() => ask(`Why: ${c.title}?`)}><Sparkles size={15} aria-hidden />Ask why</button>
                    )}
                  </div>
                </motion.article>
              );
            })}
          </AnimatePresence>

          {data && (
            <div className="flex flex-col items-center gap-1.5 px-5 pb-2 pt-7 text-center">
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-green/[0.14] text-green"><Check size={22} strokeWidth={2.4} /></span>
              <h2 className="mt-1.5 text-[20px] font-semibold tracking-[-0.02em]">You're all caught up</h2>
              <p className="text-[14px] text-muted">{data.summary.total} updates · {data.summary.needs_you} needed you · {data.summary.handled} handled</p>
            </div>
          )}
        </section>

        <aside aria-label="Today" className="flex min-w-[260px] flex-[0_1_300px] flex-col gap-4 md:pt-[58px]">
          <div className="card px-[18px] pb-1.5 pt-4">
            <h2 className="mb-1.5 text-[15px] font-semibold">Today</h2>
            {[
              ["Need you", data?.summary.needs_you ?? "–", "text-accent-ink"],
              ["In progress", stats.doing, ""],
              ["Closed in 24h", stats.closed, ""],
              ["Written by Relay", `${tasks.data?.auto_written_pct ?? "–"}%`, "text-green"],
            ].map(([label, v, tone]) => (
              <div key={label as string} className="flex items-center justify-between border-t border-line/[0.07] py-2.5">
                <span className="text-[14px] text-fg2">{label}</span>
                <span className={cn("text-[20px] font-semibold tabular-nums", tone as string)}>{v}</span>
              </div>
            ))}
          </div>
          <button onClick={() => ask()} className="card flex flex-col gap-2.5 px-[18px] py-4 text-left transition hover:shadow-lift">
            <span className="flex items-center gap-2 text-[15px] font-semibold"><Sparkles size={18} className="text-purple" aria-hidden />Ask Relay</span>
            <span className="flex h-[38px] items-center rounded-[10px] px-3 text-[14px] text-muted fill">What's blocked this week?<span className="kbd ml-auto">⌘K</span></span>
            <span className="text-[12.5px] text-muted">Answers from tasks, emails, commits and SOPs you can see.</span>
          </button>
          {stats.due.length > 0 && (
            <div className="card px-[18px] pb-2 pt-4">
              <h2 className="mb-1 text-[15px] font-semibold">Due soon</h2>
              {stats.due.map((t) => (
                <Link key={t.id} to={`/tasks?task=${t.id}`} className="flex gap-3 border-t border-line/[0.07] py-2.5">
                  <span className="w-1 rounded-sm" style={{ background: t.team?.color }} />
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate text-[14px] font-medium">{t.title}</span>
                    <span className="text-[12.5px] text-muted">{[t.team?.name, firstName(t.assignee?.name), dueLabel(t.due_at)].filter(Boolean).join(" · ")}</span>
                  </span>
                </Link>
              ))}
            </div>
          )}
          <button onClick={refresh} className="btn btn-ghost self-start text-[12.5px] text-muted">Refresh feed</button>
        </aside>
      </div>

      <Dialog open={!!story} onClose={() => setStory(null)} title={story?.name ?? "Team"}>
        {story && (
          <div className="flex flex-col gap-3 p-5">
            <div className="flex items-center gap-2.5">
              <TeamDot color={story.color} className="h-3 w-3" />
              <h2 className="text-[20px] font-semibold tracking-[-0.02em]">{story.name}</h2>
              <span className="ml-auto text-[13px] capitalize text-muted">{story.health === "green" ? "All good" : story.health === "red" ? "Something is broken" : "Something is stuck"}</span>
            </div>
            {story.items.length === 0 && <p className="py-6 text-center text-[14px] text-muted">Nothing new from this team today.</p>}
            {story.items.map((c) => (
              <div key={c.id} className="rounded-[14px] p-3.5 fill">
                <span className="caption">{KIND[c.kind]?.label}</span>
                <p className="mt-0.5 text-[15px] font-semibold leading-snug">{c.title}</p>
                <p className="mt-0.5 text-[13.5px] text-fg2">{c.body}</p>
              </div>
            ))}
          </div>
        )}
      </Dialog>
    </Page>
  );
}

function Bars({ values }: { values: number[] }) {
  const max = Math.max(...values, 1);
  const days = ["M", "T", "W", "T", "F", "S", "S"];
  return (
    <div role="img" aria-label={`Failures per day: ${values.join(", ")}`} className="mt-3.5 flex h-[92px] items-end gap-2.5 rounded-xl px-3.5 pb-2.5 pt-3 fill">
      {values.map((v, i) => (
        <div key={i} className="flex h-full flex-1 flex-col items-center justify-end gap-1.5">
          <div className={cn("w-full max-w-[28px] rounded-[5px]", i === values.length - 1 ? "bg-accent" : "fill-2")} style={{ height: `${Math.max(6, (v / max) * 80)}%` }} />
          <span className="text-[11px] text-muted">{days[i]}</span>
        </div>
      ))}
    </div>
  );
}
