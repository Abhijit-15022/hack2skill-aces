import { motion } from "framer-motion";
import { Bot, Check, GitPullRequest, RotateCcw, Search, ShieldCheck, Zap } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Page } from "../components/Layout";
import { Badge, Empty, ErrorNote, PageHeader, Spinner, spring } from "../components/ui";
import { api, useApi } from "../lib/api";
import { useSession } from "../lib/session";
import { cn, firstName, timeAgo } from "../lib/utils";

const STATUS: Record<string, [string, any]> = {
  open: ["Open", "red"], investigating: ["Investigating…", "blue"], fix_proposed: ["Fix raised · waiting for review", "orange"],
  verifying: ["Rerunning the pipeline…", "blue"], resolved: ["Resolved", "green"], needs_human: ["Needs a person", "red"],
};

export default function OnCall() {
  const { id } = useParams();
  const nav = useNavigate();
  const list = useApi<{ incidents: any[] }>("/incidents", 3000);
  const current = id ?? list.data?.incidents[0]?.id;

  return (
    <Page className="max-w-[1280px]">
      <PageHeader title="On-call" subtitle="Pipeline failures investigated by the on-call agent. A person approves every fix." />
      {list.error && <ErrorNote message={list.error} />}
      {list.data && list.data.incidents.length === 0 && (
        <Empty title="No failures" icon={<Zap size={20} />}>When a pipeline fails, the agent opens an incident here within seconds.</Empty>
      )}
      <div className="flex flex-wrap items-start gap-6">
        {list.data && list.data.incidents.length > 0 && (
          <nav aria-label="Incidents" className="flex w-full flex-col gap-1.5 xl:w-[220px]">
            {list.data.incidents.map((i) => (
              <button key={i.id} onClick={() => nav(`/oncall/${i.id}`)}
                className={cn("flex flex-col gap-0.5 rounded-xl px-3 py-2.5 text-left transition", String(i.id) === String(current) ? "card" : "hover:fill")}>
                <span className="flex items-center gap-2 text-[13.5px] font-semibold">
                  <span className={cn("h-2 w-2 rounded-full", i.status === "resolved" ? "bg-green" : "bg-red")} />{i.key} · {i.flow_id}
                </span>
                <span className="pl-4 text-[12px] text-muted">{STATUS[i.status]?.[0]} · {timeAgo(i.detected_at)}</span>
              </button>
            ))}
          </nav>
        )}
        {current && <IncidentView id={Number(current)} />}
      </div>
    </Page>
  );
}

function IncidentView({ id }: { id: number }) {
  const { data: i, error, setData } = useApi<any>(`/incidents/${id}`, 3000);
  const [replay, setReplay] = useState(0);
  const [busy, setBusy] = useState(false);
  const { users } = useSession();

  if (error) return <ErrorNote message={error} />;
  if (!i) return <div className="flex flex-1 justify-center py-16"><Spinner /></div>;
  const [label, tone] = STATUS[i.status] ?? [i.status, "gray"];
  const fix = i.fix ?? {};
  const fixLabel = fix.pr_number ? `PR #${fix.pr_number}` : "Proposed fix";
  const fixRef = fix.pr_number ? `PR #${fix.pr_number}` : "the fix";
  const reviewer = users.find((u) => u.id === i.review_task?.assignee?.id) ?? i.review_task?.assignee;
  const total = i.steps.length ? i.steps[i.steps.length - 1].t : 0;

  const act = async (action: "approve" | "reject") => {
    setBusy(true);
    try {
      setData({ ...i, ...(await api(`/incidents/${id}/${action}`, { body: action === "reject" ? { reason: "Needs a different fix" } : {} })) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-[1_1_640px] flex-col gap-5">
      <header className="flex flex-col gap-2.5">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-[28px] font-bold leading-tight tracking-[-0.024em]">{i.flow_id} failed</h2>
          <Badge tone={tone} className="h-6 px-2.5 text-[12.5px]">{i.status === "resolved" && <Check size={13} strokeWidth={2.6} />}{label}</Badge>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span className="chip">{i.key}</span>
          <span className="chip">Pipeline · {i.namespace}.{i.flow_id}</span>
          <span className="chip">Detected {new Date(i.detected_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
          {i.owners?.business && <span className="chip">Business owner · {i.owners.business.name}</span>}
          {i.owners?.tech && <span className="chip">Tech owner · {i.owners.tech.name}</span>}
          <span className="chip bg-red/10 text-red">Severity · {i.severity}</span>
        </div>
      </header>

      {i.status === "resolved" && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={spring} className="flex items-center gap-3 rounded-2xl bg-green/[0.14] px-[18px] py-3.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#1A7431] text-white"><Check size={15} strokeWidth={2.6} /></span>
          <div className="flex flex-col"><strong className="text-[14.5px] font-semibold">Fixed. {i.flow_id} reran and passed.</strong>
            <span className="text-[13px] text-fg2">{i.key} and its review task are closed. Resolved {timeAgo(i.resolved_at)} after detection.</span></div>
        </motion.div>
      )}

      <div className="flex flex-wrap items-start gap-6">
        <section className="flex min-w-0 flex-[1_1_440px] flex-col gap-5">
          <div data-tour="oncall-investigation" className="card px-[22px] pb-2 pt-[18px]">
            <div className="mb-2 flex items-center gap-2.5">
              <span className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-[#1D1D1F] text-white"><Bot size={16} /></span>
              <div className="flex flex-col leading-tight">
                <h3 className="text-[16px] font-semibold">Investigation by the on-call agent</h3>
                <span className="text-[12.5px] text-muted">{i.status === "investigating" ? "Investigating…" : `${i.steps.length} steps · ${total < 1 ? "under a second" : `${total.toFixed(0)} s`}`}</span>
              </div>
              <button className="btn btn-secondary ml-auto" onClick={() => setReplay((r) => r + 1)}><RotateCcw size={14} />Replay</button>
            </div>
            <ol key={replay}>
              {i.steps.map((s: any, n: number) => (
                <motion.li key={n} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: replay ? n * 0.55 : n * 0.06 }}
                  className="grid grid-cols-[28px_1fr_auto] gap-3 border-t border-line/[0.07] py-3.5">
                  <span className={cn("flex h-7 w-7 items-center justify-center rounded-full", s.found ? "bg-orange/[0.14] text-orange" : "bg-green/[0.14] text-green")}>
                    {s.found ? <Search size={14} strokeWidth={2.4} /> : <Check size={14} strokeWidth={2.6} />}
                  </span>
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="text-[14.5px] font-semibold">{s.title}</span>
                    <span className="text-[13.5px] leading-normal text-fg2">{s.detail}</span>
                    {s.code && <code className="mt-1 overflow-x-auto whitespace-pre rounded-lg border border-line/[0.07] fill px-3 py-2 font-mono text-[12.5px]">{s.code}</code>}
                  </div>
                  <span className="text-[12px] tabular-nums text-muted">{s.t.toFixed(1)}s</span>
                </motion.li>
              ))}
            </ol>
          </div>

          {i.impact.length > 0 && (
            <div className="card flex flex-col gap-3.5 px-[22px] pb-5 pt-[18px]">
              <h3 className="text-[16px] font-semibold">What this failure affects</h3>
              <div className="flex items-center overflow-x-auto pb-1" role="img" aria-label={`Downstream: ${i.impact.map((x: any) => x.name).join(", ")}`}>
                <Node name={i.fix?.model ?? i.flow_id} state="Failed" tone="red" />
                {i.impact.map((x: any) => (
                  <div key={x.name} className="flex items-center">
                    <span className="relative h-px w-8 bg-line/[0.15] after:absolute after:-right-px after:-top-[3.5px] after:border-y-4 after:border-l-[6px] after:border-y-transparent after:border-l-line/[0.15]" />
                    <Node name={x.name} state={x.state === "stale" ? "Stale" : "Skipped"} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {fix.diff && (
            <div data-tour="oncall-fix" className="card overflow-hidden">
              <div className="flex flex-wrap items-center gap-2.5 border-b border-line/[0.07] px-[18px] py-3.5">
                <GitPullRequest size={18} aria-hidden />
                <h3 className="text-[15px] font-semibold">{fixLabel} · {i.root_cause_title}</h3>
                <span className="ml-auto text-[12.5px] text-muted">{fix.path} · +{fix.added} −{fix.removed}</span>
                {fix.pr_url && <a className="btn btn-ghost btn-sm" href={fix.pr_url} target="_blank" rel="noreferrer">Open on GitHub</a>}
              </div>
              <pre className="overflow-x-auto py-2.5 font-mono text-[12.5px] leading-relaxed">
                {fix.diff.split("\n").slice(2).map((ln: string, n: number) => (
                  <div key={n} className={cn("px-4", ln.startsWith("+") && "bg-green/[0.14]", ln.startsWith("-") && "bg-red/10", ln.startsWith("@@") && "text-muted")}>{ln || " "}</div>
                ))}
              </pre>
            </div>
          )}
        </section>

        <aside className="flex min-w-[280px] flex-[0_1_320px] flex-col gap-4" aria-label="Decision">
          {i.root_cause_title && (
            <div className="card flex flex-col gap-2.5 px-5 py-[18px]">
              <span className="caption">Root cause</span>
              <h3 className="text-[19px] font-bold leading-snug tracking-[-0.018em]">{i.root_cause_title}</h3>
              <p className="text-[14px] leading-normal text-fg2">{i.root_cause}</p>
              {i.confidence != null && (
                <div className="flex items-center gap-2 text-[13px]">
                  <span className="flex gap-[3px]" aria-hidden>{[0.4, 0.7, 0.85].map((th) => <span key={th} className={cn("h-1.5 w-[18px] rounded-sm", i.confidence >= th ? "bg-[#1A7431]" : "fill-2")} />)}</span>
                  <span className="text-fg2">{i.confidence >= 0.85 ? "High" : i.confidence >= 0.6 ? "Medium" : "Low"} confidence</span>
                </div>
              )}
            </div>
          )}
          {i.status !== "resolved" && i.fix?.diff && (
            <div className="card px-5 pb-3 pt-[18px]">
              <h3 className="mb-1.5 text-[15px] font-semibold">What happens next</h3>
              {[
                <><strong className="font-semibold">{firstName(reviewer?.name) || "The owner"} reviews {fixRef}.</strong> {i.review_task && <Link className="text-accent-ink" to={`/tasks?task=${i.review_task.id}`}>{i.review_task.key}</Link>} was created for them.</>,
                <>On approval, Relay <strong className="font-semibold">reruns {i.flow_id}</strong>.</>,
                <>If it passes, {i.key} closes and {i.owners?.business?.name ?? "the business owner"} <strong className="font-semibold">is told</strong>.</>,
              ].map((txt, n) => (
                <div key={n} className="grid grid-cols-[24px_1fr] gap-2.5 py-2 text-[14px]"><span className="flex h-6 w-6 items-center justify-center rounded-full fill text-[12px] font-semibold">{n + 1}</span><span>{txt}</span></div>
              ))}
              <div className="mt-2 flex items-center gap-2 rounded-[10px] px-3 py-2.5 text-[12.5px] text-fg2 fill">
                <ShieldCheck size={15} aria-hidden />
                <span>{i.owners?.tech?.name ?? "Owner"} setting: <strong className="font-semibold">{i.autonomy === "act" ? "AI acts, then tells" : i.autonomy === "suggest" ? "AI suggests only" : "AI drafts, a person approves"}.</strong> <Link className="text-accent-ink" to="/admin">Change</Link></span>
              </div>
            </div>
          )}
          {i.status === "fix_proposed" && (
            <div className="flex flex-col gap-2">
              <button className="btn btn-primary btn-lg" disabled={busy} onClick={() => act("approve")}>{fix.pr_number ? `Approve & merge ${fixRef}` : "Approve & apply the fix"}</button>
              <button className="btn btn-secondary btn-lg" disabled={busy} onClick={() => act("reject")}>Request changes</button>
              <span className="text-center text-[12px] text-muted">Every action is recorded in the audit log.</span>
            </div>
          )}
          {i.status === "verifying" && <div className="card flex items-center gap-3 px-5 py-4 text-[14px]"><Spinner />Rerunning {i.flow_id}…</div>}
        </aside>
      </div>
    </div>
  );
}

function Node({ name, state, tone }: { name: string; state: string; tone?: "red" }) {
  return (
    <div className={cn("flex min-w-[132px] flex-col gap-0.5 rounded-xl border px-3 py-2.5", tone === "red" ? "border-red bg-red/10" : "border-line/[0.12] bg-surface")}>
      <span className="font-mono text-[12.5px] font-semibold">{name}</span>
      <span className={cn("text-[12px]", tone === "red" ? "font-semibold text-red" : "text-muted")}>{state}</span>
    </div>
  );
}
