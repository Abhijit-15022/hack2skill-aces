import { motion } from "framer-motion";
import { AudioLines, Check, CircleAlert, Lightbulb, ListPlus, PencilLine, Sparkles, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Page } from "../components/Layout";
import { ErrorNote, PageHeader, spring } from "../components/ui";
import { api, useApi } from "../lib/api";
import { cn, timeAgo } from "../lib/utils";

type Meeting = { id: number; title: string; status: string; summary: string; error: string | null; file_name: string; created_at: string;
  result: { decisions?: { text: string; why: string; said_by?: string; at?: string }[]; created?: { task_id: number; key: string; title: string; owner: string | null; due: string | null }[];
    updated?: { task_id: number; key: string; title: string; update: string }[] } };

export default function Meetings() {
  const list = useApi<{ meetings: Meeting[] }>("/meetings");
  const [current, setCurrent] = useState<Meeting | null>(null);
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const poll = useRef<number | null>(null);

  useEffect(() => () => { if (poll.current) clearInterval(poll.current); }, []);
  useEffect(() => { if (!current && list.data?.meetings[0]) setCurrent(list.data.meetings[0]); }, [list.data, current]);

  const watch = (mt: Meeting) => {
    setCurrent(mt);
    if (poll.current) clearInterval(poll.current);
    poll.current = window.setInterval(async () => {
      const r = await api<Meeting>(`/meetings/${mt.id}`);
      setCurrent(r);
      if (r.status !== "processing") {
        clearInterval(poll.current!);
        list.refresh();
      }
    }, 2500);
  };
  const upload = async () => {
    if (!file) return;
    setErr(null);
    const form = new FormData();
    form.set("title", title);
    form.set("file", file);
    try {
      watch(await api<Meeting>("/meetings", { form }));
      setFile(null);
      setTitle("");
    } catch (e: any) {
      setErr(e.message);
    }
  };
  const sample = async () => {
    setErr(null);
    try {
      watch(await api<Meeting>("/demo/meeting/sample", { body: {} }));
    } catch (e: any) {
      setErr(e.message);
    }
  };

  return (
    <Page>
      <PageHeader title="Meetings" subtitle="Drop a recording. Relay updates the tasks discussed, records decisions and assigns follow-ups." />
      <div className="flex flex-wrap items-start gap-6">
        <div className="flex min-w-[280px] flex-[1_1_320px] flex-col gap-4 lg:max-w-[380px]">
          <div className="card flex flex-col gap-3 p-5">
            <label onDragOver={(e) => (e.preventDefault(), setDrag(true))} onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); setFile(e.dataTransfer.files?.[0] ?? null); }}
              className={cn("flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-[1.5px] border-dashed px-5 py-8 text-center transition",
                drag ? "border-accent bg-accent/[0.06]" : "border-line/[0.15] hover:fill")}>
              <Upload size={22} className="text-muted" />
              <span className="text-[14.5px] font-medium">{file ? file.name : "Drop a meeting recording"}</span>
              <span className="text-[12.5px] text-muted">wav, mp3, m4a, ogg or webm</span>
              <input type="file" accept="audio/*" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </label>
            <label className="label" htmlFor="mt-title">Title (optional)</label>
            <input id="mt-title" className="input -mt-1" placeholder="e.g. Data and Finance sync" value={title} onChange={(e) => setTitle(e.target.value)} />
            <button className="btn btn-primary" disabled={!file} onClick={upload}><AudioLines size={16} />Process recording</button>
            {err && <ErrorNote message={err} />}
          </div>
          <div className="card flex flex-col gap-3 p-5">
            <span className="caption">Try it with a sample</span>
            <p className="text-[14px] text-fg2">A 64-second Data and Finance sync with five people, two decisions and a task handed over.</p>
            <audio controls src="/api/demo/meeting/sample.wav" className="w-full" aria-label="Sample meeting recording" />
            <button className="btn btn-secondary" onClick={sample}><Sparkles size={15} />Process the sample</button>
          </div>
          {list.data && list.data.meetings.length > 0 && (
            <nav aria-label="Past meetings" className="card overflow-hidden">
              <p className="caption px-4 pb-1 pt-3.5">Earlier</p>
              {list.data.meetings.map((mt) => (
                <button key={mt.id} onClick={() => setCurrent(mt)} className={cn("flex w-full flex-col border-t border-line/[0.07] px-4 py-2.5 text-left transition hover:fill",
                  current?.id === mt.id && "fill")}>
                  <span className="text-[14px] font-medium">{mt.title}</span>
                  <span className="text-[12px] text-muted">{mt.status === "done" ? `${mt.result.created?.length ?? 0} tasks · ${mt.result.decisions?.length ?? 0} decisions` : mt.status} · {timeAgo(mt.created_at)}</span>
                </button>
              ))}
            </nav>
          )}
        </div>
        <section className="min-w-0 flex-[2_1_520px]" aria-live="polite">
          {current ? <Result mt={current} /> : (
            <div className="card flex flex-col items-center gap-2 px-6 py-16 text-center">
              <AudioLines size={24} className="text-muted" />
              <p className="text-[17px] font-semibold">No meetings yet</p>
              <p className="max-w-sm text-[14px] text-muted">Process the sample to see decisions and tasks appear.</p>
            </div>
          )}
        </section>
      </div>
    </Page>
  );
}

function Result({ mt }: { mt: Meeting }) {
  if (mt.status === "processing")
    return (
      <div className="card flex flex-col items-center gap-3 px-6 py-16 text-center">
        <motion.div animate={{ scale: [1, 1.08, 1] }} transition={{ repeat: Infinity, duration: 1.6 }} className="flex h-14 w-14 items-center justify-center rounded-full bg-purple/[0.12] text-purple">
          <AudioLines size={26} />
        </motion.div>
        <p className="text-[17px] font-semibold">Gemini is listening to “{mt.title}”</p>
        <p className="text-[14px] text-muted">Finding decisions, owners and task updates. About half a minute.</p>
      </div>
    );
  if (mt.status === "failed")
    return <div className="card flex items-start gap-3 px-5 py-4 text-[15px]"><CircleAlert size={18} className="mt-0.5 text-red" />{mt.error}</div>;
  const r = mt.result;
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={spring} className="flex flex-col gap-4">
      <div className="card flex flex-col gap-2 px-5 py-[18px]">
        <span className="caption">{mt.file_name} · {timeAgo(mt.created_at)}</span>
        <h2 className="text-[24px] font-bold tracking-[-0.02em]">{mt.title}</h2>
        <p className="text-[15.5px] leading-relaxed text-fg2">{mt.summary}</p>
      </div>
      <Section icon={Lightbulb} title="Decisions" count={r.decisions?.length ?? 0} tone="text-purple">
        {r.decisions?.map((d, i) => (
          <li key={i} className="flex gap-3 px-5 py-3">
            {d.at && <span className="mt-0.5 h-fit rounded-md fill px-1.5 font-mono text-[12px] tabular-nums text-muted">{d.at}</span>}
            <span><span className="text-[15px] font-medium">{d.text}</span><span className="block text-[13.5px] text-muted">Why: {d.why}{d.said_by ? ` · ${d.said_by}` : ""}</span></span>
          </li>
        ))}
      </Section>
      <Section icon={ListPlus} title="New tasks" count={r.created?.length ?? 0} tone="text-green">
        {r.created?.map((c) => (
          <li key={c.task_id} className="flex flex-wrap items-center gap-2 px-5 py-3">
            <Check size={15} className="text-green" />
            <Link to={`/tasks?task=${c.task_id}`} className="text-[15px] font-medium hover:underline">{c.title}</Link>
            <span className="text-[13px] text-muted">{c.key}{c.owner ? ` · ${c.owner}` : ""}{c.due ? ` · due ${new Date(c.due).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}` : ""}</span>
          </li>
        ))}
      </Section>
      <Section icon={PencilLine} title="Tasks updated" count={r.updated?.length ?? 0} tone="text-accent-ink">
        {r.updated?.map((u, i) => (
          <li key={i} className="flex flex-col px-5 py-3">
            <Link to={`/tasks?task=${u.task_id}`} className="text-[15px] font-medium hover:underline">{u.key} · {u.title}</Link>
            <span className="text-[13.5px] text-muted">{u.update}</span>
          </li>
        ))}
      </Section>
    </motion.div>
  );
}

function Section({ icon: Icon, title, count, tone, children }: { icon: any; title: string; count: number; tone: string; children: React.ReactNode }) {
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center gap-2 px-5 py-3.5"><Icon size={17} className={tone} /><h3 className="text-[15px] font-semibold">{title}</h3><span className="text-[13px] text-muted">{count}</span></div>
      {count === 0 ? <p className="border-t border-line/[0.07] px-5 py-3 text-[14px] text-muted">None</p> : <ul className="[&>li]:border-t [&>li]:border-line/[0.07]">{children}</ul>}
    </div>
  );
}
