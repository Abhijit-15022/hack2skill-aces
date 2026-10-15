import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, GripVertical, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Page } from "../components/Layout";
import { Badge, Dialog, Empty, ErrorNote, Segmented, Spinner, spring, Switch } from "../components/ui";
import { api, useApi } from "../lib/api";
import { useSession } from "../lib/session";
import { cn } from "../lib/utils";

type Step = { id?: number; title: string; owner_team_id: number | null; owner_role: string | null; evidence_type: string;
  evidence_hint: string; due_offset_days: number; depends_on: number[]; needs_approval: boolean; notes?: string };
const EVIDENCE = ["email", "calendar", "file", "task", "manual"] as const;
const HINT: Record<string, string> = {
  email: "Matched when an email with the expected subject or attachment arrives.",
  calendar: "Matched when a calendar invite with a similar title is sent.",
  file: "Matched when a file is uploaded to the project.",
  task: "Matched when the linked task is closed.",
  manual: "Someone ticks it off by hand.",
};

export default function Sops() {
  const { id } = useParams();
  const list = useApi<{ sops: any[] }>("/sops");
  const [drafting, setDrafting] = useState(false);
  const nav = useNavigate();
  const visible = list.data?.sops.filter((s) => s.status !== "superseded") ?? [];
  const current = id ?? visible[0]?.id;

  return (
    <div className="flex min-h-screen flex-wrap">
      <nav aria-label="SOPs" className="material flex w-full flex-col gap-1 border-r border-line/[0.07] px-3 py-6 lg:sticky lg:top-0 lg:h-screen lg:w-[260px]">
        <div className="flex items-center justify-between px-2 pb-2">
          <h1 className="text-[22px] font-bold tracking-[-0.02em]">SOPs</h1>
          <button className="btn btn-ghost h-8 w-8 px-0" aria-label="New SOP" onClick={() => setDrafting(true)}><Plus size={18} /></button>
        </div>
        {visible.map((s) => (
          <Link key={s.id} to={`/sops/${s.id}`} className={cn("flex flex-col gap-0.5 rounded-xl px-3 py-2.5 transition", String(s.id) === String(current) ? "card" : "hover:fill")}>
            <span className="text-[13.5px] font-semibold">{s.title}</span>
            <span className="text-[12px] text-muted">{s.team} · v{s.version}{s.status === "draft" ? " · draft" : ""}</span>
          </Link>
        ))}
      </nav>
      <div className="min-w-0 flex-1">
        {list.error && <Page><ErrorNote message={list.error} /></Page>}
        {current ? <SopEditor key={current} id={Number(current)} onSaved={(newId) => { list.refresh(); if (String(newId) !== String(current)) nav(`/sops/${newId}`); }} onNew={() => setDrafting(true)} />
          : list.data && <Page><Empty title="No SOPs yet">Upload a document or describe a process and Relay drafts the steps.</Empty></Page>}
      </div>
      <DraftDialog open={drafting} onClose={() => setDrafting(false)} onCreated={(newId) => { list.refresh(); nav(`/sops/${newId}`); }} />
    </div>
  );
}

function SopEditor({ id, onSaved, onNew }: { id: number; onSaved: (id: number) => void; onNew: () => void }) {
  const { data, error, setData } = useApi<any>(`/sops/${id}`);
  const { teams } = useSession();
  const [steps, setSteps] = useState<Step[]>([]);
  const [title, setTitle] = useState("");
  const [open, setOpen] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dismissed, setDismissed] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setSteps(data.steps);
    setTitle(data.title);
    setDirty(false);
  }, [data]);

  if (error) return <Page><ErrorNote message={error} /></Page>;
  if (!data) return <Page><div className="flex justify-center py-16"><Spinner /></div></Page>;

  const edit = (i: number, patch: Partial<Step>) => {
    setSteps((s) => s.map((x, j) => (j === i ? { ...x, ...patch } : x)));
    setDirty(true);
  };
  const move = (i: number, to: number) => {
    setSteps((s) => {
      const copy = [...s];
      const [item] = copy.splice(i, 1);
      copy.splice(to, 0, item);
      return copy;
    });
    setOpen(to);
    setDirty(true);
  };
  const save = async (next = steps, nextTitle = title) => {
    setBusy(true);
    try {
      const saved = await api(`/sops/${id}`, { method: "PUT", body: { title: nextTitle, steps: next } });
      setDirty(false);
      setMsg(saved.id !== id ? `Saved as draft v${saved.version}. Running projects stay on v${data.version}.` : "Saved.");
      if (saved.id === id) setData(saved);
      onSaved(saved.id);
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };
  const publish = async () => {
    if (dirty) await save();
    setBusy(true);
    try {
      setData(await api(`/sops/${id}/publish`, { body: {} }));
      setMsg("Published. New projects use this version.");
      onSaved(id);
    } finally {
      setBusy(false);
    }
  };
  const apply = (s: any) => {
    const a = s.apply;
    if (!a) return;
    const idx = steps.findIndex((x) => x.id === a.step_id);
    let next = steps;
    if (a.evidence_type) next = steps.map((x, j) => (j === idx ? { ...x, evidence_type: a.evidence_type } : x));
    if (a.move_before) {
      next = [...steps];
      const [item] = next.splice(idx, 1);
      next.splice(a.move_before - 1, 0, { ...item, depends_on: item.depends_on.filter((d) => d < a.move_before) });
    }
    setSteps(next);
    setDismissed((d) => [...d, s.id]);
    save(next);
  };
  const suggestions = (data.suggestions ?? []).filter((s: any) => !dismissed.includes(s.id));

  return (
    <div className="flex flex-wrap">
      <Page className="min-w-0 flex-[999_1_520px] max-w-[860px]">
        <header className="flex flex-wrap items-start gap-4">
          <div className="flex min-w-[260px] flex-1 flex-col gap-1.5">
            <div className="flex flex-wrap gap-2">
              <Badge tone={data.status === "published" ? "green" : "orange"}>{data.status === "published" ? `Published v${data.version}` : `Draft v${data.version}`}</Badge>
              {dirty && <Badge tone="orange">Unsaved changes</Badge>}
              <span className="text-[12.5px] text-muted">{data.projects} project{data.projects === 1 ? "" : "s"} use this</span>
            </div>
            <label htmlFor="sop-title" className="sr-only">Title</label>
            <input id="sop-title" value={title} onChange={(e) => (setTitle(e.target.value), setDirty(true))}
              className="bg-transparent text-[30px] font-bold leading-tight tracking-[-0.024em] outline-none" />
            {data.description && <p className="max-w-[620px] text-[14px] text-fg2">{data.description}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-secondary" onClick={onNew}><Sparkles size={15} />Draft with AI</button>
            <button className="btn btn-secondary" disabled={!dirty || busy} onClick={() => save()}>Save</button>
            <button className="btn btn-primary" disabled={busy} onClick={publish}>Publish</button>
          </div>
        </header>
        {data.source_file && (
          <div className="flex items-center gap-3 rounded-[14px] px-3.5 py-3 text-[13.5px] fill">
            <Upload size={16} aria-hidden /><span>Started from <strong className="font-semibold">{data.source_file}</strong></span>
            <span className="ml-auto text-muted">Owner team · {data.team}</span>
          </div>
        )}
        {msg && <p className="text-[13px] text-muted" role="status">{msg}</p>}

        <ol className="flex flex-col gap-2.5" aria-label="Steps">
          {steps.map((s, i) => {
            const isOpen = open === i;
            return (
              <motion.li layout transition={spring} key={s.id ?? `new-${i}`} className={cn("rounded-2xl border bg-surface shadow-card transition-shadow", isOpen ? "border-line/[0.12] shadow-lift" : "border-line/[0.07]")}>
                <div className="flex items-center gap-3 px-4 py-3.5">
                  <span className="flex flex-col text-muted">
                    <button aria-label="Move up" disabled={i === 0} onClick={() => move(i, i - 1)} className="disabled:opacity-30"><GripVertical size={16} /></button>
                  </span>
                  <span className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-lg text-[12.5px] font-semibold fill">{i + 1}</span>
                  <button className="flex min-w-0 flex-1 flex-col text-left" onClick={() => setOpen(isOpen ? -1 : i)} aria-expanded={isOpen}>
                    <span className="text-[15px] font-semibold">{s.title || "Untitled step"}</span>
                    <span className="truncate text-[12.5px] text-muted">
                      {teams.find((t) => t.id === s.owner_team_id)?.name ?? s.owner_role ?? "No owner"} · day {s.due_offset_days} · done when: {s.evidence_type}{s.needs_approval ? " · needs approval" : ""}
                    </span>
                  </button>
                  <ChevronDown size={16} className={cn("shrink-0 text-muted transition-transform duration-300 ease-apple", isOpen && "rotate-180")} />
                </div>
                <AnimatePresence initial={false}>
                  {isOpen && (
                    <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={spring} className="overflow-hidden">
                      <div className="grid grid-cols-1 gap-x-5 gap-y-3.5 px-4 pb-[18px] sm:grid-cols-2 sm:pl-[70px]">
                        <div><label className="label" htmlFor={`st-${i}`}>Step title</label><input id={`st-${i}`} className="input" value={s.title} onChange={(e) => edit(i, { title: e.target.value })} /></div>
                        <div><label className="label" htmlFor={`so-${i}`}>Owner team</label>
                          <select id={`so-${i}`} className="input" value={s.owner_team_id ?? ""} onChange={(e) => edit(i, { owner_team_id: Number(e.target.value) || null })}>
                            <option value="">{s.owner_role ? `Role: ${s.owner_role}` : "None"}</option>{teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                          </select></div>
                        <div className="sm:col-span-2"><span className="label">How Relay knows it's done</span>
                          <Segmented size="sm" label={`Evidence ${i}`} value={s.evidence_type} onChange={(v) => edit(i, { evidence_type: v })}
                            options={EVIDENCE.map((e) => ({ value: e, label: e[0].toUpperCase() + e.slice(1) }))} />
                          <p className="mt-2 text-[12.5px] text-muted">{HINT[s.evidence_type]}</p></div>
                        <div className="sm:col-span-2"><label className="label" htmlFor={`sh-${i}`}>What proves it</label>
                          <input id={`sh-${i}`} className="input" placeholder="e.g. email with the signed offer letter attached" value={s.evidence_hint} onChange={(e) => edit(i, { evidence_hint: e.target.value })} /></div>
                        <div><label className="label" htmlFor={`sd-${i}`}>Due (days after start)</label>
                          <input id={`sd-${i}`} type="number" min={0} className="input" value={s.due_offset_days} onChange={(e) => edit(i, { due_offset_days: Number(e.target.value) })} /></div>
                        <div><span className="label">Depends on</span>
                          <div className="flex min-h-9 flex-wrap items-center gap-1.5">
                            {steps.slice(0, i).map((_, j) => {
                              const on = s.depends_on.includes(j + 1);
                              return <button key={j} onClick={() => edit(i, { depends_on: on ? s.depends_on.filter((d) => d !== j + 1) : [...s.depends_on, j + 1] })}
                                className={cn("chip", on && "bg-accent/10 text-accent-ink")}>Step {j + 1}</button>;
                            })}
                            {i === 0 && <span className="text-[13px] text-muted">First step</span>}
                          </div></div>
                        <div className="flex items-center gap-3 rounded-xl px-3.5 py-3 fill sm:col-span-2">
                          <span className="flex flex-1 flex-col"><span className="text-[14px] font-medium">Needs approval</span><span className="text-[12.5px] text-muted">A named person must approve before this step counts as done.</span></span>
                          <Switch label="Needs approval" checked={s.needs_approval} onChange={(v) => edit(i, { needs_approval: v })} />
                        </div>
                        <button className="btn btn-ghost justify-self-start text-red sm:col-span-2" onClick={() => (setSteps((x) => x.filter((_, j) => j !== i)), setDirty(true), setOpen(-1))}><Trash2 size={14} />Remove step</button>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.li>
            );
          })}
        </ol>
        <button className="btn btn-ghost self-start" onClick={() => {
          setSteps((s) => [...s, { title: "", owner_team_id: data.team_id, owner_role: null, evidence_type: "manual", evidence_hint: "", due_offset_days: 0, depends_on: s.length ? [s.length] : [], needs_approval: false }]);
          setOpen(steps.length);
          setDirty(true);
        }}><Plus size={16} />Add step</button>
      </Page>

      <aside aria-label="Suggestions" className="material flex min-w-[280px] flex-[1_1_300px] flex-col gap-3 border-l border-line/[0.07] px-6 py-8 lg:sticky lg:top-0 lg:h-screen lg:max-w-[340px]">
        <div className="flex items-center gap-2">
          <Sparkles size={18} className="text-purple" aria-hidden /><h2 className="text-[15px] font-semibold">Suggestions</h2>
          <span className="ml-auto text-[12.5px] text-muted">{suggestions.length} open</span>
        </div>
        <AnimatePresence>
          {suggestions.map((s: any) => (
            <motion.div key={s.id} layout initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }} transition={spring}
              className="flex flex-col gap-2 rounded-[14px] border border-line/[0.07] bg-surface p-3.5">
              <span className="caption">{s.kind}</span>
              <span className="text-[14px] leading-snug">{s.text}</span>
              <span className="flex gap-1.5">
                {s.apply && <button className="btn btn-primary btn-sm" onClick={() => apply(s)}>Apply</button>}
                <button className="btn btn-ghost btn-sm" onClick={() => setDismissed((d) => [...d, s.id])}>Dismiss</button>
              </span>
            </motion.div>
          ))}
        </AnimatePresence>
        {suggestions.length === 0 && <p className="px-2 py-5 text-center text-[13.5px] text-muted">No suggestions. This SOP looks complete.</p>}
        <p className="mt-auto rounded-xl px-3.5 py-3 text-[12.5px] leading-normal text-fg2 fill">
          Projects already running keep their version. Editing a published SOP that's in use creates a new draft version. Every change is in the audit log.
        </p>
      </aside>
    </div>
  );
}

function DraftDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: number) => void }) {
  const { me, teams } = useSession();
  const [mode, setMode] = useState<"describe" | "upload">("describe");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [team, setTeam] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const myTeams = me?.user.is_org_admin ? teams : teams.filter((t) => me?.teams.some((m) => m.id === t.id));

  const submit = async () => {
    const form = new FormData();
    form.set("team_id", team || String(myTeams[0]?.id ?? ""));
    if (mode === "upload" && file) form.set("file", file);
    else form.set("text", text);
    setBusy(true);
    setErr(null);
    try {
      const sop = await api("/sops/draft", { form });
      onClose();
      setText("");
      setFile(null);
      onCreated(sop.id);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Draft an SOP with AI">
      <div className="flex flex-col gap-4 p-6">
        <div className="flex items-center gap-2"><Sparkles size={20} className="text-purple" /><h2 className="text-[20px] font-semibold tracking-[-0.02em]">Draft an SOP with AI</h2></div>
        <Segmented label="Draft source" value={mode} onChange={setMode} options={[{ value: "describe", label: "Describe it" }, { value: "upload", label: "Upload a document" }]} />
        {mode === "describe" ? (
          <div><label className="label" htmlFor="dd-text">Describe the process in plain English</label>
            <textarea id="dd-text" rows={6} className="input h-auto py-2.5" placeholder="Vendor onboarding: collect KYC by email, verify bank details, finance approval, add to ERP…" value={text} onChange={(e) => setText(e.target.value)} /></div>
        ) : (
          <label className="flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-[1.5px] border-dashed border-line/[0.15] px-6 py-8 text-center transition hover:fill">
            <Upload size={22} className="text-muted" />
            <span className="text-[14px] font-medium">{file ? file.name : "Choose a PDF or text file"}</span>
            <span className="text-[12.5px] text-muted">Relay reads it and drafts the steps. You review before publishing.</span>
            <input type="file" accept=".pdf,.txt,.md" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
        )}
        <div><label className="label" htmlFor="dd-team">Owner team</label>
          <select id="dd-team" className="input" value={team} onChange={(e) => setTeam(e.target.value)}>
            {myTeams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select></div>
        {err && <ErrorNote message={err} />}
        <div className="flex justify-end gap-2">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || (mode === "describe" ? !text.trim() : !file)} onClick={submit}>{busy ? <Spinner className="text-white" /> : "Draft steps"}</button>
        </div>
      </div>
    </Dialog>
  );
}
