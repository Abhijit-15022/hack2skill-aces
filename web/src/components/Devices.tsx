import { Laptop, Plug } from "lucide-react";
import { useApi } from "../lib/api";
import { cn, timeAgo } from "../lib/utils";
import { Avatar } from "./ui";

export type Device = { id: number; user: { id: number; name: string; initials: string; color: string }; hostname: string; platform: string;
  version: string; online: boolean; last_seen_at: string; last_sync_at: string | null; sessions_sent: number;
  tools: { tool: string; label: string; found: boolean; sessions_7d: number; last_session_at: string | null; error?: string | null }[] };

export function ToolList({ d }: { d: Device }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {d.tools.map((t) => (
        <li key={t.tool} className="flex items-center gap-2 text-[13.5px]">
          <span className={cn("h-2 w-2 shrink-0 rounded-full", t.error ? "bg-orange" : t.found ? "bg-green" : "fill-2")} aria-hidden />
          <span className={cn("flex-1", !t.found && "text-muted")}>{t.label}</span>
          <span className="text-[12px] text-muted">
            {t.error ? "can't read" : t.found ? `${t.sessions_7d} this week` : "not installed"}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Today page card: is my relay-agent running, and which AI coding tools does it see? */
export function ConnectedTools() {
  const { data } = useApi<{ devices: Device[] }>("/me/devices", 60000);
  if (!data) return null;
  const d = data.devices[0];
  return (
    <div data-tour="devices" className="card px-[18px] pb-4 pt-4">
      <div className="mb-2.5 flex items-center gap-2">
        <Plug size={16} aria-hidden /><h2 className="text-[15px] font-semibold">Connected tools</h2>
        {d && <span className={cn("ml-auto flex items-center gap-1.5 text-[12px]", d.online ? "text-green" : "text-muted")}>
          <span className={cn("h-2 w-2 rounded-full", d.online ? "bg-green" : "fill-2")} />{d.online ? "Live" : `Last seen ${timeAgo(d.last_seen_at)}`}
        </span>}
      </div>
      {d ? (
        <>
          <ToolList d={d} />
          <p className="mt-3 flex items-center gap-1.5 border-t border-line/[0.07] pt-2.5 text-[12px] text-muted">
            <Laptop size={13} aria-hidden />{d.hostname} · {d.last_sync_at ? `synced ${timeAgo(d.last_sync_at)}` : "not synced yet"}
          </p>
        </>
      ) : (
        <div className="flex flex-col gap-2 text-[13.5px] text-fg2">
          <p>Connect Claude Code, Cursor, Codex and Antigravity so your tasks update themselves.</p>
          <code className="block overflow-x-auto whitespace-pre rounded-lg px-3 py-2 font-mono text-[12px] fill">python3 agent/relay_agent.py status</code>
        </div>
      )}
    </div>
  );
}

export function DeviceRow({ d }: { d: Device }) {
  return (
    <div className="flex flex-wrap items-start gap-4 border-t border-line/[0.07] px-[18px] py-4 first:border-0">
      <div className="flex min-w-[200px] flex-1 items-center gap-3">
        <Avatar user={{ ...d.user, kind: "human" }} size={32} />
        <div className="flex flex-col leading-tight">
          <span className="text-[14.5px] font-semibold">{d.user.name}</span>
          <span className="text-[12.5px] text-muted">{d.hostname} · {d.platform} · agent {d.version}</span>
        </div>
      </div>
      <div className="min-w-[240px] flex-1"><ToolList d={d} /></div>
      <div className="flex min-w-[140px] flex-col items-end gap-0.5 text-[12.5px]">
        <span className={cn("flex items-center gap-1.5 font-medium", d.online ? "text-green" : "text-muted")}>
          <span className={cn("h-2 w-2 rounded-full", d.online ? "bg-green" : "fill-2")} />{d.online ? "Live" : "Offline"}
        </span>
        <span className="text-muted">seen {timeAgo(d.last_seen_at)}</span>
        <span className="text-muted">{d.sessions_sent} sessions sent</span>
      </div>
    </div>
  );
}
