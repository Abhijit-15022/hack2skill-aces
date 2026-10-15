import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, ChevronRight, MousePointer2, Pause, Play, RotateCcw, Sparkles, X } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, BASE, getToken, setToken } from "../lib/api";
import { useSession } from "../lib/session";
import { cn } from "../lib/utils";
import { spring } from "./ui";

/** Demo mode: a guided tour that signs in as each demo person, clicks through Relay and explains what's on screen. */

type Step = {
  as?: string; // sign in as this person first
  route?: string; // then open this page
  run?: string; // then call this demo endpoint (as the admin)
  ask?: string; // or open Ask with this question
  click?: string; // then click this element, like a person would
  target?: string; // and highlight this one
  title: string;
  body: string;
  dwell?: number; // ms on screen when playing
};

const ADMIN = "kavya@acme.test";

const STEPS: Step[] = [
  { title: "Relay in three minutes",
    body: "I'll sign in as four people at Acme and click through for you: an engineer, a Finance lead, the head of Operations, and the on-call agent. Press pause any time to try things yourself.",
    dwell: 6500 },

  { as: "abhijit@acme.test", route: "/", target: '[data-tour="devices"]', title: "relay-agent on Abhijit's laptop",
    body: "A small agent found Claude Code, Cursor and Antigravity on this laptop and checks in every few minutes. It reads recent AI coding sessions, removes secrets on the laptop, and sends them to Relay. Nobody writes a status update." },
  { target: '[data-tour="questions"]', title: "One question instead of a status meeting",
    body: "Relay read Abhijit's Cursor session, worked out which task it belonged to, and created one when none matched. The one thing it can't guess is what \"done\" means, so it asks, with a suggestion taken from the session." },
  { route: "/tasks", click: '[role="tablist"][aria-label="Whose tasks"] [role="tab"]:nth-child(2)', target: '[data-tour="task-blocked"]',
    title: "Blocked, without anyone saying so",
    body: "In that session the AI hit \"permission denied for schema finance\". Relay marked the task Blocked and told Abhijit's lead." },
  { click: '[data-tour="task-blocked"]', target: '[data-tour="task-blockers"]', title: "What it's waiting on, and who",
    body: "The blocker names who it's waiting on and where it was found. Relay also wrote the description from the session. Resolving the blocker clears the badge everywhere." },
  { target: '[data-tour="task-timeline"]', title: "Every update has a source",
    body: "AI sessions, commits, meetings and emails each leave a line here, so a manager can see where any status came from." },

  { as: "meera@acme.test", route: "/", target: '[data-tour="plan"]', title: "Meera's day, planned at 7:00",
    body: "Gemini ranks Meera's open work by urgency and impact. Estimates come from how long similar tasks really took. Focus time is booked in the gaps between meetings, and each task lists what she'll need." },
  { target: '[data-tour="timeline"]', title: "Meetings and focus on one line",
    body: "Relay books the blue focus blocks around her meetings, which come from her calendar." },
  { run: "/demo/focus/meera@acme.test", target: '[data-tour="focus-banner"]', title: "Focus Guard",
    body: "Meera is focusing and five pings just arrived. Kudos, a newsletter and two replies wait until she's done. Only the pipeline failure gets through, because it blocks Finance today.", dwell: 7500 },
  { target: '[data-tour="inbox"]', title: "Held, with a reason",
    body: "Held messages are delivered when the focus block ends. Anything that got through says why." },

  { as: ADMIN, route: "/team", target: '[data-tour="team-headline"]', title: "Kavya's view: who needs help",
    body: "Kavya leads Operations. Instead of chasing updates, she gets a summary of each team from tasks, calendars and AI sessions." },
  { target: '[data-tour="team-action"]', title: "Signals, with a fix to apply",
    body: "Overload, a review stuck for 30 hours, work with no feedback. Late nights show only for people who chose to share them. Each signal comes with a suggested action Kavya can apply in one click." },
  { click: '[role="tablist"][aria-label="Team view"] [role="tab"]:nth-child(2)', target: '[data-tour="standup"]', title: "A written standup",
    body: "Relay writes each person's yesterday, today and blockers from logged work, so the team can skip the daily call." },
  { route: "/meetings", click: 'nav[aria-label="Past meetings"] button', target: '[data-tour="meeting-result"]', title: "A meeting becomes tasks",
    body: "Relay processed a 64-second recording of a Data and Finance sync. Out came decisions with timestamps, a new \"schema change check\" task for Abhijit due Friday, and a request handed from Meera to Ananya.",
    dwell: 8000 },
  { route: "/oncall", target: '[data-tour="oncall-investigation"]', title: "The on-call agent",
    body: "orders_daily failed overnight. The agent traced it to a renamed column, linked it to the task where the rename happened, and recalled the last similar incident, all in seconds.",
    dwell: 8000 },
  { target: '[data-tour="oncall-fix"]', title: "A person approves every fix",
    body: "The agent drafts the fix and shows what's affected downstream. An engineer approves it, and Relay reruns the pipeline to check it's green." },
  { ask: "What is Abhijit working on, and is anything blocked?", target: '[data-tour="ask"]', title: "Ask anything (⌘K)",
    body: "Plain-language questions about the team's work, answered from tasks, AI sessions, emails, commits and meetings. Each answer cites its sources.",
    dwell: 14000 },
  { route: "/admin", click: '[role="tablist"][aria-label="Admin sections"] [role="tab"]:nth-child(4)', target: '[data-tour="connections"]',
    title: "Which laptops are connected",
    body: "Every laptop running relay-agent, the tools it found, and when it last checked in. A laptop shows Live if it checked in within 15 minutes. Only metadata is shown here, never session content." },
  { title: "That's Relay",
    body: "Tasks that update themselves from AI coding sessions, meetings and email; a planned day with protected focus; and managers who see progress and blockers without asking. Admin → Demo has a button for each event if you want to trigger them live.",
    dwell: 9000 },
];

type Rect = { top: number; left: number; width: number; height: number };
const TourCtx = createContext<{ start: () => void; active: boolean }>({ start: () => {}, active: false });
export const useTour = () => useContext(TourCtx);

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function waitFor(selector: string, ms: number, alive: () => boolean): Promise<HTMLElement | null> {
  const until = Date.now() + ms;
  while (alive() && Date.now() < until) {
    const el = document.querySelector<HTMLElement>(selector);
    if (el && el.getBoundingClientRect().height > 0) return el;
    await pause(150);
  }
  return null;
}

async function asAdmin(path: string) {
  const login = await fetch(`${BASE}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: ADMIN }) });
  const { token } = await login.json();
  await fetch(`${BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: "{}" });
}

export function TourProvider({ children }: { children: ReactNode }) {
  const { me, signIn, reload } = useSession();
  const nav = useNavigate();
  const [active, setActive] = useState(false);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [ready, setReady] = useState(false);
  const [busyText, setBusyText] = useState<string | null>(null);
  const [rect, setRect] = useState<Rect | null>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number; down: boolean } | null>(null);
  const run = useRef(0);
  const origToken = useRef<string | null>(null);
  const meEmail = useRef<string | undefined>(undefined);
  const targetEl = useRef<HTMLElement | null>(null);
  meEmail.current = me?.user.email;

  const start = useCallback(() => {
    origToken.current = getToken();
    setIdx(0);
    setPlaying(true);
    setActive(true);
  }, []);

  const stop = useCallback(async () => {
    run.current++;
    setActive(false);
    setRect(null);
    setCursor(null);
    window.dispatchEvent(new Event("relay:ask-close"));
    if (origToken.current && origToken.current !== getToken()) {
      setToken(origToken.current);
      await reload();
    }
    nav("/");
  }, [nav, reload]);

  // Play one step: sign in, open the page, act, then find what to highlight.
  useEffect(() => {
    if (!active) return;
    const id = ++run.current;
    const alive = () => run.current === id;
    const step = STEPS[idx];
    setReady(false);
    setRect(null);
    targetEl.current = null;
    (async () => {
      if (!step.ask) window.dispatchEvent(new Event("relay:ask-close"));
      if (step.as && step.as !== meEmail.current) {
        setBusyText(`Signing in as ${step.as.split("@")[0].replace(/^./, (c) => c.toUpperCase())}…`);
        await signIn(step.as);
        if (!alive()) return;
      }
      if (step.route) nav(step.route);
      if (step.run) {
        setBusyText("Setting the scene…");
        // Focus is already on after seed-demo or an earlier run: don't send the pings again.
        const inFocus = step.run.startsWith("/demo/focus") && (await api("/me/notifications").catch(() => null))?.focus?.active;
        if (!inFocus) await asAdmin(step.run).catch(() => {});
      }
      setBusyText(null);
      if (step.ask) {
        await pause(400);
        window.dispatchEvent(new CustomEvent("relay:ask", { detail: step.ask }));
      }
      if (step.click) {
        const el = await waitFor(step.click, 8000, alive);
        if (!alive()) return;
        if (el) {
          el.scrollIntoView({ block: "center", behavior: "smooth" });
          await pause(350);
          const r = el.getBoundingClientRect();
          setCursor((c) => ({ x: c?.x ?? window.innerWidth / 2, y: c?.y ?? window.innerHeight - 80, down: false }));
          await pause(50);
          setCursor({ x: r.left + r.width / 2, y: r.top + r.height / 2, down: false });
          await pause(750);
          if (!alive()) return;
          setCursor({ x: r.left + r.width / 2, y: r.top + r.height / 2, down: true });
          await pause(160);
          el.click();
          setCursor({ x: r.left + r.width / 2, y: r.top + r.height / 2, down: false });
        }
      }
      if (step.target) {
        const el = await waitFor(step.target, 12000, alive);
        if (!alive()) return;
        if (el) {
          targetEl.current = el;
          const tall = el.getBoundingClientRect().height > window.innerHeight * 0.6;
          el.scrollIntoView({ block: tall ? "start" : "center", behavior: "smooth" });
          await pause(450);
        }
      } else {
        setCursor(null);
      }
      if (alive()) setReady(true);
    })();
  }, [active, idx]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the spotlight on its element while the page loads, scrolls and resizes.
  useEffect(() => {
    if (!active) return;
    const tick = () => {
      const el = targetEl.current;
      if (!el || !el.isConnected) {
        if (el && !el.isConnected) {
          const again = STEPS[idx].target && document.querySelector<HTMLElement>(STEPS[idx].target!);
          targetEl.current = again || null;
        }
        if (!targetEl.current) return setRect(null);
      }
      const r = targetEl.current!.getBoundingClientRect();
      setRect((p) => (p && Math.abs(p.top - r.top) < 1 && Math.abs(p.left - r.left) < 1 && Math.abs(p.width - r.width) < 1 && Math.abs(p.height - r.height) < 1
        ? p : { top: r.top, left: r.left, width: r.width, height: r.height }));
    };
    const iv = setInterval(tick, 120);
    window.addEventListener("resize", tick);
    return () => {
      clearInterval(iv);
      window.removeEventListener("resize", tick);
    };
  }, [active, idx]);

  const next = useCallback(() => setIdx((i) => Math.min(i + 1, STEPS.length - 1)), []);
  const back = useCallback(() => setIdx((i) => Math.max(i - 1, 0)), []);

  // Auto-advance while playing.
  const dwell = STEPS[idx]?.dwell ?? 6500;
  const last = idx === STEPS.length - 1;
  useEffect(() => {
    if (!active || !playing || !ready || last) return;
    const t = setTimeout(next, dwell);
    return () => clearTimeout(t);
  }, [active, playing, ready, idx, dwell, last, next]);

  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea")) return;
      if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") back();
      else if (e.key === " ") {
        e.preventDefault();
        setPlaying((p) => !p);
      } else if (e.key === "Escape") stop();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [active, next, back, stop]);

  return (
    <TourCtx.Provider value={{ start, active }}>
      {children}
      {active && (
        <TourLayer step={STEPS[idx]} idx={idx} rect={rect} cursor={cursor} ready={ready} playing={playing} busyText={busyText} dwell={dwell}
          who={me ? `${me.user.name}${me.user.title ? ` · ${me.user.title}` : ""}` : undefined}
          onNext={next} onBack={back} onToggle={() => setPlaying((p) => !p)} onExit={stop} onRestart={() => (setIdx(0), setPlaying(true))} />
      )}
    </TourCtx.Provider>
  );
}

function TourLayer({ step, idx, rect, cursor, ready, playing, busyText, dwell, who, onNext, onBack, onToggle, onExit, onRestart }: {
  step: Step; idx: number; rect: Rect | null; cursor: { x: number; y: number; down: boolean } | null; ready: boolean; playing: boolean;
  busyText: string | null; dwell: number; who?: string; onNext: () => void; onBack: () => void; onToggle: () => void; onExit: () => void; onRestart: () => void;
}) {
  const card = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const [vw, setVw] = useState(window.innerWidth);
  const last = idx === STEPS.length - 1;
  const PAD = 8;

  useEffect(() => {
    const on = () => setVw(window.innerWidth);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  // Place the card next to the highlight: below, above, beside, or pinned to the bottom when there's no room.
  useLayoutEffect(() => {
    const W = window.innerWidth, H = window.innerHeight;
    const cw = card.current?.offsetWidth ?? 380, ch = card.current?.offsetHeight ?? 230;
    if (!rect || W < 720) return setPos(null);
    const clampX = (x: number) => Math.min(Math.max(16, x), W - cw - 16);
    const clampY = (y: number) => Math.min(Math.max(16, y), H - ch - 16);
    if (rect.top + rect.height + PAD + 14 + ch < H) setPos({ top: rect.top + rect.height + PAD + 14, left: clampX(rect.left) });
    else if (rect.top - PAD - 14 - ch > 0) setPos({ top: rect.top - PAD - 14 - ch, left: clampX(rect.left) });
    else if (rect.left + rect.width + PAD + 14 + cw < W) setPos({ top: clampY(rect.top), left: rect.left + rect.width + PAD + 14 });
    else if (rect.left - PAD - 14 - cw > 0) setPos({ top: clampY(rect.top), left: rect.left - PAD - 14 - cw });
    else setPos(null);
  }, [rect, idx, ready, vw]);

  const centered = !rect;
  return (
    <div className="fixed inset-0" style={{ zIndex: 200 }} role="dialog" aria-modal="false" aria-label="Demo mode">
      {/* While playing, the page is for watching; pause to click around. */}
      {playing && <div className="absolute inset-0" />}
      <AnimatePresence>
        {rect ? (
          <motion.div key="spot" initial={{ opacity: 0 }} transition={spring}
            animate={{ opacity: 1, top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 }}
            className="pointer-events-none absolute rounded-[18px] ring-2 ring-accent/70"
            style={{ boxShadow: "0 0 0 9999px rgba(0,0,0,0.42)" }} />
        ) : (
          <motion.div key="dim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="pointer-events-none absolute inset-0 bg-black/40" />
        )}
      </AnimatePresence>

      {cursor && (
        <motion.div className="pointer-events-none absolute left-0 top-0" initial={false}
          animate={{ x: cursor.x - 4, y: cursor.y - 3, scale: cursor.down ? 0.82 : 1 }}
          transition={{ type: "spring", bounce: 0.15, duration: 0.7 }}>
          <MousePointer2 size={26} className="fill-white text-black drop-shadow-[0_2px_4px_rgba(0,0,0,0.35)]" strokeWidth={1.6} />
          <AnimatePresence>
            {cursor.down && <motion.span key="ripple" initial={{ scale: 0.3, opacity: 0.7 }} animate={{ scale: 2.2, opacity: 0 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.5 }} className="absolute -left-3 -top-3 h-8 w-8 rounded-full bg-accent/50" />}
          </AnimatePresence>
        </motion.div>
      )}

      <div ref={card}
        className={cn("material absolute flex w-[380px] max-w-[calc(100vw-32px)] flex-col gap-3 rounded-[20px] border border-line/[0.1] p-5 shadow-lift",
          "transition-[top,left] duration-500 ease-apple", !pos && (centered ? "inset-x-0 top-[28%] mx-auto" : "inset-x-0 bottom-6 mx-auto"))}
        style={pos ? { top: pos.top, left: pos.left } : undefined}>
        <div className="flex items-center gap-2">
          <span className="flex h-6 items-center gap-1.5 rounded-full bg-accent/10 px-2.5 text-[12px] font-semibold text-accent-ink"><Sparkles size={12} />Demo mode</span>
          <span className="text-[12px] tabular-nums text-muted">{idx + 1} of {STEPS.length}</span>
          <button onClick={onExit} aria-label="Exit demo mode" className="btn btn-ghost ml-auto h-7 w-7 px-0 text-muted"><X size={15} /></button>
        </div>
        {who && idx > 0 && !last && <span className="text-[12.5px] font-medium text-muted">Signed in as {who}</span>}
        <AnimatePresence mode="wait">
          <motion.div key={idx} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.2 }} className="flex flex-col gap-1.5">
            <h2 className="text-[19px] font-semibold leading-snug tracking-[-0.018em]">{step.title}</h2>
            <p className="text-[14.5px] leading-relaxed text-fg2">{step.body}</p>
          </motion.div>
        </AnimatePresence>
        {busyText && <p className="text-[13px] text-muted">{busyText}</p>}
        {!ready && !busyText && <p className="text-[13px] text-muted">Opening…</p>}
        {!playing && !last && <p className="text-[12.5px] text-muted">Paused. Click around, then press play or Next.</p>}
        <div className="h-[3px] overflow-hidden rounded-full fill-2" aria-hidden>
          {playing && ready && !last && (
            <motion.div key={`bar-${idx}`} className="h-full bg-accent" initial={{ width: "0%" }} animate={{ width: "100%" }} transition={{ duration: dwell / 1000, ease: "linear" }} />
          )}
          {last && <div className="h-full w-full bg-accent" />}
        </div>
        <div className="flex items-center gap-2">
          <button className="btn btn-ghost h-9 w-9 px-0" onClick={onBack} disabled={idx === 0} aria-label="Back"><ChevronLeft size={18} /></button>
          {!last && (
            <button className="btn btn-secondary h-9 w-9 px-0" onClick={onToggle} aria-label={playing ? "Pause" : "Play"}>
              {playing ? <Pause size={15} fill="currentColor" /> : <Play size={15} fill="currentColor" />}
            </button>
          )}
          <span className="hidden flex-1 text-center text-[11.5px] text-muted sm:block">← → · space · esc</span>
          {last ? (
            <>
              <button className="btn btn-secondary ml-auto" onClick={onRestart}><RotateCcw size={14} />Again</button>
              <button className="btn btn-primary" onClick={onExit}>Finish</button>
            </>
          ) : (
            <button className="btn btn-primary ml-auto" onClick={onNext}>Next<ChevronRight size={16} /></button>
          )}
        </div>
      </div>
    </div>
  );
}
