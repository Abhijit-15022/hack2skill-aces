import { motion } from "framer-motion";
import { ArrowUp, ShieldCheck, Sparkles } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useSession } from "../lib/session";
import { Dialog, Spinner } from "./ui";

type Source = { type: string; id: number; task_id?: number; title: string; meta: string; n: number };
type Answer = { answer: string; segments: { text: string; cite: number }[]; sources: Source[]; searched?: number };

const SUGGESTIONS = [
  "Why did we change the orders model?",
  "What's pending from Finance this week?",
  "Where is Rahul Menon's onboarding?",
  "What did the Data team work on recently?",
];

const AskCtx = createContext<(q?: string) => void>(() => {});
export const useAsk = () => useContext(AskCtx);

export function AskProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [seed, setSeed] = useState<string | undefined>();
  const openAsk = useCallback((q?: string) => {
    setSeed(q);
    setOpen(true);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    // Demo mode opens and closes Ask from outside the layout.
    const onAsk = (e: Event) => openAsk((e as CustomEvent<string>).detail);
    const onClose = () => setOpen(false);
    window.addEventListener("keydown", onKey);
    window.addEventListener("relay:ask", onAsk);
    window.addEventListener("relay:ask-close", onClose);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("relay:ask", onAsk);
      window.removeEventListener("relay:ask-close", onClose);
    };
  }, [openAsk]);

  return (
    <AskCtx.Provider value={openAsk}>
      {children}
      <Dialog open={open} onClose={() => setOpen(false)} title="Ask Relay" wide>
        <AskPanel seed={seed} onNavigate={() => setOpen(false)} />
      </Dialog>
    </AskCtx.Provider>
  );
}

function AskPanel({ seed, onNavigate }: { seed?: string; onNavigate: () => void }) {
  const [q, setQ] = useState(seed ?? "");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const nav = useNavigate();
  const { me } = useSession();

  const ask = useCallback(async (question: string) => {
    if (!question.trim()) return;
    setQ(question);
    setBusy(true);
    setError(null);
    try {
      setAnswer(await api<Answer>("/ask", { body: { question } }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    inputRef.current?.focus();
    if (seed) ask(seed);
  }, [seed, ask]);

  const go = (s: Source) => {
    onNavigate();
    if (s.type === "incident") nav(`/oncall/${s.id}`);
    else if (s.type === "sop") nav(`/sops/${s.id}`);
    else nav(`/tasks?task=${s.type === "task" ? s.id : s.task_id ?? ""}`);
  };

  return (
    <div data-tour="ask">
      <form onSubmit={(e) => (e.preventDefault(), ask(q))} className="flex items-center gap-3 border-b border-line/[0.07] px-5 py-4">
        <Sparkles size={22} className="shrink-0 text-purple" aria-hidden />
        <label htmlFor="ask-input" className="sr-only">Ask a question</label>
        <input
          id="ask-input"
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Ask anything about your team's work"
          className="min-w-0 flex-1 bg-transparent text-[20px] font-medium tracking-[-0.018em] outline-none placeholder:text-muted"
        />
        {busy ? <Spinner /> : (
          <button type="submit" aria-label="Ask" className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-white transition-transform active:scale-90 disabled:opacity-40" disabled={!q.trim()}>
            <ArrowUp size={16} />
          </button>
        )}
      </form>
      <div className="flex items-center gap-2 border-b border-line/[0.07] px-5 py-2.5 text-[12.5px] text-muted">
        <ShieldCheck size={14} aria-hidden />
        Searching tasks, AI coding sessions, emails, commits, meetings and SOPs {me?.user.is_org_admin ? "across the company" : "from teams you can see"}.
      </div>

      <div className="max-h-[56vh] overflow-y-auto">
        {error && <p className="px-5 py-4 text-[14px] text-red">{error}</p>}
        {answer && !busy && (
          <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4 px-5 pb-2 pt-5">
            <p className="text-[16.5px] leading-relaxed tracking-[-0.012em]">
              {answer.segments.length ? answer.segments.map((s, i) => (
                <span key={i}>
                  {s.text}
                  {s.cite > 0 && <span className="mx-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] bg-accent/10 px-1 align-[2px] text-[11px] font-semibold text-accent-ink">{s.cite}</span>}
                </span>
              )) : answer.answer}
            </p>
            {answer.sources.length > 0 && (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-2">
                {answer.sources.map((s) => (
                  <button key={`${s.type}-${s.id}`} onClick={() => go(s)} className="flex items-start gap-2.5 rounded-[14px] p-3 text-left fill transition hover:bg-[rgba(118,118,128,0.14)] active:scale-[0.98]">
                    <span className="mt-0.5 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] bg-accent/10 px-1 text-[11px] font-semibold text-accent-ink">{s.n}</span>
                    <span className="min-w-0">
                      <span className="block text-[13.5px] font-semibold leading-snug">{s.title}</span>
                      <span className="block truncate text-[12px] text-muted">{s.meta}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </motion.div>
        )}
        <div className="flex flex-col gap-2.5 px-5 pb-5 pt-4">
          <span className="caption">Try asking</span>
          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS.filter((s) => s !== q).slice(0, 3).map((s) => (
              <button key={s} onClick={() => ask(s)} className="h-[34px] rounded-full border border-line/[0.12] px-3.5 text-[13.5px] transition hover:fill active:scale-[0.96]">{s}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-4 border-t border-line/[0.07] px-5 py-3 text-[12px] text-muted">
        <span className="flex items-center gap-1.5"><span className="kbd">↵</span>Ask</span>
        <span className="flex items-center gap-1.5"><span className="kbd">esc</span>Close</span>
        <span className="ml-auto">Answers cite their sources · Powered by Gemini</span>
      </div>
    </div>
  );
}
