import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CalendarClock, Check, Clock, HeartPulse, Lock, MessageSquareQuote, Moon, RefreshCw, Sparkles, UserRoundCheck } from "lucide-react";
import { useState } from "react";
import { Page } from "../components/Layout";
import { Avatar, Badge, Empty, ErrorNote, PageHeader, Segmented, Spinner, spring, TeamDot } from "../components/ui";
import { api, useApi } from "../lib/api";
import { cn, firstName } from "../lib/utils";

type Signal = { kind: string; level: string; text: string; task_id?: number };
type Person = { user: { id: number; name: string; initials: string; color: string; title: string; shares_wellbeing: boolean; kind?: string };
  level: "high" | "watch" | "ok"; open_tasks: number; requests: number; overdue: number; committed_min: number; capacity_min: number; load: number;
  after_hours_nights: number | null; signals: Signal[]; action: null | { type: string; task_id: number; to_user_id: number | null; label: string; text: string } };
type TeamH = { team: { id: number; name: string; color: string; short: string }; headline: string; by_ai: boolean; people: Person[] };

const LEVEL = { high: { label: "Needs help", tone: "red" as const, icon: AlertTriangle }, watch: { label: "Watch", tone: "orange" as const, icon: Clock },
  ok: { label: "OK", tone: "green" as const, icon: Check } };
const SIGNAL_ICON: Record<string, any> = { overload: HeartPulse, after_hours: Moon, review_stuck: UserRoundCheck, no_feedback: MessageSquareQuote, overdue: CalendarClock };
const h = (m: number) => `${Math.round(m / 60)} h`;

export default function Team() {
  const [tab, setTab] = useState<"health" | "standup">("health");
  const { data, error, refresh } = useApi<{ teams: TeamH[] }>("/health/teams");
  const [teamId, setTeamId] = useState<number | null>(null);
  const teams = data?.teams ?? [];
  const current = teams.find((t) => t.team.id === teamId) ?? teams[0];

  return (
    <Page>
      <PageHeader title="Team" subtitle="Who needs help this week, and what everyone did, without a meeting.">
        <Segmented label="Team view" value={tab} onChange={setTab} options={[{ value: "health", label: "Health" }, { value: "standup", label: "Written standup" }]} />
      </PageHeader>
      {error && <ErrorNote message={error} />}
      {!data && !error && <div className="flex justify-center py-16"><Spinner /></div>}
      {data && teams.length === 0 && <Empty title="You don't lead a team" icon={<HeartPulse size={20} />}>Team Health shows the teams you lead.</Empty>}
      {teams.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {teams.map((t) => {
            const worst = t.people.some((p) => p.level === "high") ? "high" : t.people.some((p) => p.level === "watch") ? "watch" : "ok";
            const L = LEVEL[worst];
            return (
              <button key={t.team.id} onClick={() => setTeamId(t.team.id)} aria-pressed={current?.team.id === t.team.id}
                className={cn("chip h-8 gap-2", current?.team.id === t.team.id && "bg-fg text-bg")}>
                <TeamDot color={t.team.color} />{t.team.name}<L.icon size={13} className={cn(worst === "high" ? "text-red" : worst === "watch" ? "text-orange" : "text-green", current?.team.id === t.team.id && "text-bg")} aria-label={L.label} />
              </button>
            );
          })}
        </div>
      )}
      {current && tab === "health" && <Health t={current} onChanged={refresh} />}
      {current && tab === "standup" && <Standup teamId={current.team.id} />}
    </Page>
  );
}

function Health({ t, onChanged }: { t: TeamH; onChanged: () => void }) {
  const [done, setDone] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const apply = async (p: Person) => {
    if (!p.action) return;
    setBusy(p.user.id);
    try {
      const r = await api<{ done: string }>("/health/actions", { body: { type: p.action.type, task_id: p.action.task_id, to_user_id: p.action.to_user_id } });
      setDone((d) => ({ ...d, [p.user.id]: r.done }));
      setTimeout(onChanged, 1200);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="flex flex-col gap-4">
      <div className="card flex items-start gap-3 px-5 py-4">
        {t.by_ai ? <Sparkles size={18} className="mt-0.5 shrink-0 text-purple" aria-label="Written by Relay" /> : <HeartPulse size={18} className="mt-0.5 shrink-0 text-muted" />}
        <p className="text-[17px] font-semibold leading-snug tracking-[-0.014em]">{t.headline}</p>
      </div>
      <div className="flex flex-col gap-3">
        {t.people.map((p, i) => {
          const L = LEVEL[p.level];
          const pct = Math.min(100, Math.round((p.committed_min / Math.max(p.capacity_min, 1)) * 100));
          return (
            <motion.article key={p.user.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: i * 0.05 }} className="card px-5 py-4">
              <div className="flex flex-wrap items-center gap-3">
                <Avatar user={{ ...p.user, kind: "human" }} size={36} />
                <div className="flex min-w-[160px] flex-1 flex-col leading-tight">
                  <span className="text-[16px] font-semibold">{p.user.name}</span>
                  <span className="text-[13px] text-muted">{p.user.title}</span>
                </div>
                <Badge tone={L.tone} className="h-6 px-2.5 text-[12.5px]"><L.icon size={13} />{L.label}</Badge>
              </div>
              <div className="mt-3.5 grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
                <div className="flex flex-col gap-1.5">
                  <div className="flex justify-between text-[12.5px] text-muted"><span>Booked this week</span><span className="tabular-nums">{h(p.committed_min)} of {h(p.capacity_min)} free</span></div>
                  <div className="h-2 overflow-hidden rounded-full fill-2" role="img" aria-label={`${pct}% of free time booked`}>
                    <motion.div initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ type: "spring", bounce: 0, duration: 0.8 }}
                      className={cn("h-full rounded-full", p.load >= 1.3 ? "bg-red" : p.load >= 0.9 ? "bg-orange" : "bg-green")} />
                  </div>
                  <div className="flex flex-wrap gap-x-3 text-[12.5px] text-muted">
                    <span>{p.open_tasks} open</span><span>{p.requests} requests</span>{p.overdue > 0 && <span className="text-red">{p.overdue} overdue</span>}
                    <span className="flex items-center gap-1">{p.user.shares_wellbeing ? <><Moon size={12} />{p.after_hours_nights ?? 0} late nights</> : <><Lock size={12} />Wellbeing not shared</>}</span>
                  </div>
                </div>
                <ul className="flex flex-col gap-1.5">
                  {p.signals.length === 0 && <li className="flex items-center gap-2 text-[14px] text-muted"><Check size={15} className="text-green" />Nothing to worry about.</li>}
                  {p.signals.map((s, n) => {
                    const Icon = SIGNAL_ICON[s.kind] ?? AlertTriangle;
                    return (
                      <li key={n} className="flex items-start gap-2 text-[14px]">
                        <Icon size={15} className={cn("mt-0.5 shrink-0", s.level === "high" ? "text-red" : "text-orange")} aria-hidden />
                        <span className="text-fg2">{s.text}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
              {p.action && (
                <div className="mt-3.5 flex flex-wrap items-center gap-3 rounded-[14px] px-3.5 py-3 fill">
                  <Sparkles size={16} className="shrink-0 text-purple" aria-hidden />
                  <span className="min-w-[200px] flex-1 text-[14px]">{p.action.text}</span>
                  <AnimatePresence mode="wait">
                    {done[p.user.id]
                      ? <motion.span key="done" initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="btn btn-done"><Check size={15} />{done[p.user.id]}</motion.span>
                      : <motion.button key="go" className="btn btn-primary" disabled={busy === p.user.id} onClick={() => apply(p)}>{busy === p.user.id ? <Spinner className="h-4 w-4 text-white" /> : p.action.label}</motion.button>}
                  </AnimatePresence>
                </div>
              )}
            </motion.article>
          );
        })}
      </div>
      <p className="flex items-center gap-2 text-[12.5px] text-muted"><Lock size={13} />Workload comes from tasks and calendars. After-hours activity is shown only for people who chose to share it.</p>
    </div>
  );
}

function Standup({ teamId }: { teamId: number }) {
  const { data, error, setData } = useApi<any>(`/teams/${teamId}/standup`);
  const [busy, setBusy] = useState(false);
  const regen = async () => {
    setBusy(true);
    try {
      setData(await api(`/teams/${teamId}/standup?refresh=true`));
    } finally {
      setBusy(false);
    }
  };
  if (error) return <ErrorNote message={error} />;
  if (!data) return <div className="flex justify-center py-16"><Spinner /></div>;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="flex flex-1 items-center gap-2 text-[14px] text-muted">
          {data.by_ai && <Sparkles size={15} className="text-purple" />}Written by Relay from logged work, so the {data.team.name} team can skip the daily meeting.
        </p>
        <button className="btn btn-secondary" onClick={regen} disabled={busy}>{busy ? <Spinner className="h-4 w-4" /> : <RefreshCw size={15} />}Rewrite</button>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4">
        {data.people.map((p: any) => (
          <article key={p.user_id} className="card flex flex-col gap-3 px-5 py-4">
            <div className="flex items-center gap-2.5"><Avatar user={{ ...p, id: p.user_id, kind: "human" }} size={30} /><span className="text-[15px] font-semibold">{p.name}</span></div>
            {[["Yesterday", p.yesterday], ["Today", p.today], ["Blocked", p.blocked]].map(([label, items]: any) => (
              <div key={label} className="flex flex-col gap-1">
                <span className={cn("caption text-[11px]", label === "Blocked" && items.length && "text-red")}>{label}</span>
                {items.length === 0 ? <span className="text-[14px] text-muted">Nothing</span> :
                  <ul className="flex list-disc flex-col gap-0.5 pl-4 text-[14px] text-fg2">{items.map((x: string, n: number) => <li key={n}>{x}</li>)}</ul>}
              </div>
            ))}
          </article>
        ))}
      </div>
      <p className="text-[12.5px] text-muted">Generated {new Date(data.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {firstName(data.people[0]?.name) ? `${data.people.length} people` : ""}</p>
    </div>
  );
}
