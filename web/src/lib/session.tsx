import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";
import type { Team, User } from "../components/ui";
import { api, getToken, setToken } from "./api";

type Me = { user: User; org: { id: number; name: string; region: string }; teams: Team[] };
type Session = {
  me: Me | null;
  teams: Team[];
  users: User[];
  loading: boolean;
  signIn: (email: string) => Promise<void>;
  signOut: () => void;
  reload: () => Promise<void>;
  dark: boolean;
  setDark: (v: boolean) => void;
};

const Ctx = createContext<Session | null>(null);

function initialDark(): boolean {
  try {
    const saved = localStorage.getItem("relay.theme");
    if (saved) return saved === "dark";
  } catch {
    /* ignore */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(!!getToken());
  const [dark, setDarkState] = useState(initialDark);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const setDark = (v: boolean) => {
    setDarkState(v);
    try {
      localStorage.setItem("relay.theme", v ? "dark" : "light");
    } catch {
      /* ignore */
    }
  };

  const reload = useCallback(async () => {
    if (!getToken()) return;
    try {
      const [m, t, u] = await Promise.all([api<Me>("/me"), api<{ teams: Team[] }>("/teams"), api<{ users: User[] }>("/users")]);
      setMe(m);
      setTeams(t.teams);
      setUsers(u.users);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const signIn = async (email: string) => {
    const r = await api<{ token: string }>("/auth/login", { body: { email } });
    setToken(r.token);
    setLoading(true);
    await reload();
  };

  const signOut = () => {
    setToken(null);
    setMe(null);
    location.href = "/login";
  };

  return <Ctx.Provider value={{ me, teams, users, loading, signIn, signOut, reload, dark, setDark }}>{children}</Ctx.Provider>;
}

export function useSession() {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside SessionProvider");
  return s;
}
