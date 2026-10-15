import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 0) return inFuture(-s);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 172800) return "Yesterday";
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function inFuture(s: number): string {
  if (s < 86400) return `in ${Math.max(1, Math.floor(s / 3600))}h`;
  if (s < 172800) return "Tomorrow";
  return `in ${Math.floor(s / 86400)} days`;
}

export function dueLabel(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const days = Math.round((d.getTime() - Date.now()) / 86400000);
  if (days < 0) return `Overdue ${-days}d`;
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

export function firstName(name?: string | null) {
  return (name ?? "").split(" ")[0];
}

export const SOURCE_LABEL: Record<string, string> = {
  claude: "Claude session",
  git: "Commit",
  email: "Email",
  calendar: "Calendar",
  oncall: "On-call agent",
  manual: "Update",
  sop: "SOP",
  github: "GitHub",
  kestra: "Kestra",
};
