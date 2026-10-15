import { AudioLines, PlayCircle, ClipboardList, FolderKanban, HeartPulse, Home, LogOut, Moon, Newspaper, Search, Settings2, SquareCheckBig, Sun, Sunrise, Zap } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useApi } from "../lib/api";
import { useSession } from "../lib/session";
import { cn } from "../lib/utils";
import { AskProvider, useAsk } from "./Ask";
import { useTour } from "./Tour";
import { Avatar, TeamDot } from "./ui";

const NAV = [
  { to: "/", label: "Today", icon: Sunrise, end: true },
  { to: "/feed", label: "Feed", icon: Newspaper },
  { to: "/tasks", label: "Tasks", icon: SquareCheckBig },
  { to: "/meetings", label: "Meetings", icon: AudioLines },
  { to: "/team", label: "Team", icon: HeartPulse },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/sops", label: "SOPs", icon: ClipboardList },
  { to: "/oncall", label: "On-call", icon: Zap },
];

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <span className="flex items-center justify-center rounded-[9px] bg-fg text-bg" style={{ width: size, height: size }}>
      <svg width={size * 0.6} height={size * 0.6} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
        <path d="M5 12a7 7 0 0 1 7-7" /><path d="M19 12a7 7 0 0 1-7 7" /><circle cx="12" cy="12" r="2.2" />
      </svg>
    </span>
  );
}

function Sidebar() {
  const { me, teams, signOut, dark, setDark } = useSession();
  const ask = useAsk();
  const tour = useTour();
  const { data: inc } = useApi<{ incidents: { status: string }[] }>("/incidents", 15000);
  const openIncident = inc?.incidents.some((i) => !["resolved"].includes(i.status));
  const myTeamIds = new Set(me?.teams.map((t) => t.id));
  const shownTeams = me?.user.is_org_admin ? teams : teams.filter((t) => myTeamIds.has(t.id));

  const link = ({ isActive }: { isActive: boolean }) =>
    cn("flex h-[34px] items-center gap-2.5 rounded-lg px-2.5 text-[14px] font-medium transition-colors",
      isActive ? "fill-2 text-fg" : "text-fg2 hover:fill hover:text-fg");

  return (
    <nav aria-label="Main" className="material sticky top-0 hidden h-screen w-[244px] shrink-0 flex-col gap-0.5 border-r border-line/[0.07] px-3 py-3.5 md:flex">
      <div className="flex items-center gap-2.5 px-2 pb-3.5 pt-1">
        <Logo />
        <div className="flex min-w-0 flex-col leading-tight">
          <span className="text-[14px] font-semibold">Relay</span>
          <span className="truncate text-[12px] text-muted">{me?.org.name}</span>
        </div>
      </div>
      <button onClick={() => ask()} className="mb-2.5 flex h-[34px] items-center gap-2.5 rounded-lg px-2.5 text-[14px] font-medium text-muted fill transition hover:text-fg">
        <Search size={16} aria-hidden />Ask or search<span className="kbd ml-auto">⌘K</span>
      </button>
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} className={link}>
          <Icon size={18} strokeWidth={1.8} aria-hidden />{label}
          {to === "/oncall" && openIncident && <span className="ml-auto h-2 w-2 rounded-full bg-red" aria-label="Open failure" />}
        </NavLink>
      ))}
      {shownTeams.length > 0 && <div className="px-2.5 pb-1.5 pt-4 text-[11.5px] font-semibold text-muted">Teams</div>}
      {shownTeams.map((t) => (
        <NavLink key={t.id} to={`/tasks?team=${t.id}`} className={() => link({ isActive: false })}>
          <TeamDot color={t.color} />{t.name}
        </NavLink>
      ))}
      <div className="min-h-6 flex-1" />
      <button onClick={tour.start} className="mb-1 flex h-[34px] items-center gap-2.5 rounded-lg bg-accent/10 px-2.5 text-[14px] font-semibold text-accent-ink transition hover:bg-accent/[0.16] active:scale-[0.98]">
        <PlayCircle size={18} strokeWidth={1.9} aria-hidden />Demo mode<span className="ml-auto text-[12px] font-medium opacity-70">3 min</span>
      </button>
      {me?.user.is_org_admin && (
        <NavLink to="/admin" className={link}><Settings2 size={18} strokeWidth={1.8} aria-hidden />Admin</NavLink>
      )}
      <div className="mt-1.5 flex items-center gap-2.5 border-t border-line/[0.07] px-2 pt-2.5">
        <Avatar user={me?.user} size={30} />
        <div className="flex min-w-0 flex-1 flex-col leading-tight">
          <span className="truncate text-[13.5px] font-semibold">{me?.user.name}</span>
          <span className="truncate text-[12px] text-muted">{me?.user.title}</span>
        </div>
        <button onClick={() => setDark(!dark)} aria-label={dark ? "Light mode" : "Dark mode"} className="btn btn-ghost h-8 w-8 px-0 text-muted">
          {dark ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button onClick={signOut} aria-label="Sign out" className="btn btn-ghost h-8 w-8 px-0 text-muted"><LogOut size={16} /></button>
      </div>
    </nav>
  );
}

function TabBar() {
  const ask = useAsk();
  const tab = ({ isActive }: { isActive: boolean }) =>
    cn("flex min-w-[56px] flex-col items-center justify-center gap-0.5 text-[10.5px] font-semibold", isActive ? "text-accent" : "text-muted");
  return (
    <nav aria-label="Tabs" className="material fixed inset-x-0 bottom-0 z-20 flex h-[78px] justify-around border-t border-line/[0.07] px-2 pb-5 pt-1 md:hidden">
      <NavLink to="/" end className={tab}><Sunrise size={24} strokeWidth={1.9} />Today</NavLink>
      <NavLink to="/feed" className={tab}><Home size={24} strokeWidth={1.9} />Feed</NavLink>
      <button onClick={() => ask()} className={tab({ isActive: false })}><Search size={24} strokeWidth={1.9} />Ask</button>
      <NavLink to="/tasks" className={tab}><SquareCheckBig size={24} strokeWidth={1.9} />Tasks</NavLink>
      <NavLink to="/team" className={tab}><HeartPulse size={24} strokeWidth={1.9} />Team</NavLink>
    </nav>
  );
}

export function Layout() {
  return (
    <AskProvider>
      <div className="flex min-h-screen">
        <Sidebar />
        <main className="min-w-0 flex-1 pb-24 md:pb-0">
          <Outlet />
        </main>
        <TabBar />
      </div>
    </AskProvider>
  );
}

export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("mx-auto flex w-full max-w-[1180px] flex-col gap-5 px-4 py-6 md:px-9 md:py-8", className)}>{children}</div>;
}
