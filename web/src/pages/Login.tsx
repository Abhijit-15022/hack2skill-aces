import { motion } from "framer-motion";
import { ArrowRight, PlayCircle } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Logo } from "../components/Layout";
import { useTour } from "../components/Tour";
import { ErrorNote, spring } from "../components/ui";
import { useSession } from "../lib/session";

const DEMO = [
  { name: "Kavya Rao", email: "kavya@acme.test", role: "Head of Operations · admin", initials: "KR", color: "#5E5CE6" },
  { name: "Rohan Iyer", email: "rohan@acme.test", role: "Data Platform lead", initials: "RI", color: "#1D4ED8" },
  { name: "Abhijit Singh", email: "abhijit@acme.test", role: "Data engineer", initials: "AS", color: "#0058B0" },
  { name: "Meera Rao", email: "meera@acme.test", role: "Finance lead", initials: "MR", color: "#B25E00" },
  { name: "Priya Shah", email: "priya@acme.test", role: "People lead", initials: "PS", color: "#1A7431" },
  { name: "Grace Hopper", email: "grace@globex.test", role: "Globex · a different company", initials: "GH", color: "#7E3BA0" },
];

export default function Login() {
  const { signIn } = useSession();
  const nav = useNavigate();
  const tour = useTour();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const go = async (e: string) => {
    setError(null);
    try {
      await signIn(e);
      nav("/");
    } catch (err: any) {
      setError(err.message);
    }
  };
  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-12">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={spring} className="flex w-full max-w-[440px] flex-col gap-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <Logo size={48} />
          <h1 className="text-[34px] font-bold tracking-[-0.03em]">Relay</h1>
          <p className="text-[16px] text-fg2">The task manager that updates itself.</p>
        </div>
        <button onClick={tour.start} className="card flex items-center gap-3.5 px-4 py-3.5 text-left transition hover:shadow-lift active:scale-[0.99]">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-white"><PlayCircle size={22} /></span>
          <span className="flex flex-1 flex-col leading-tight">
            <span className="text-[15px] font-semibold">Watch the demo</span>
            <span className="text-[13px] text-muted">A guided three-minute tour. Relay clicks through and explains each part.</span>
          </span>
          <ArrowRight size={16} className="text-muted" />
        </button>
        <form onSubmit={(e) => (e.preventDefault(), go(email))} className="flex gap-2">
          <label htmlFor="email" className="sr-only">Work email</label>
          <input id="email" type="email" className="input h-11 text-[15px]" placeholder="Work email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <button className="btn btn-primary h-11 w-11 px-0" aria-label="Sign in" disabled={!email}><ArrowRight size={18} /></button>
        </form>
        {error && <ErrorNote message={error} />}
        <div className="card overflow-hidden">
          <p className="caption px-4 pb-1 pt-3.5">Demo accounts</p>
          {DEMO.map((d) => (
            <button key={d.email} onClick={() => go(d.email)} className="flex w-full items-center gap-3 border-t border-line/[0.07] px-4 py-3 text-left transition first:border-0 hover:fill active:scale-[0.99]">
              <span className="flex h-9 w-9 items-center justify-center rounded-full text-[13px] font-semibold text-white" style={{ background: d.color }}>{d.initials}</span>
              <span className="flex flex-1 flex-col leading-tight"><span className="text-[14.5px] font-semibold">{d.name}</span><span className="text-[12.5px] text-muted">{d.role}</span></span>
              <ArrowRight size={16} className="text-muted" />
            </button>
          ))}
        </div>
        <p className="text-center text-[12px] text-muted">Demo sign-in by email. Production uses Google Workspace sign-in.</p>
      </motion.div>
    </div>
  );
}
