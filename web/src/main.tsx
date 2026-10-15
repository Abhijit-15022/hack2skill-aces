import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import "./index.css";
import { getToken } from "./lib/api";
import { SessionProvider, useSession } from "./lib/session";
import Admin from "./pages/Admin";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Meetings from "./pages/Meetings";
import OnCall from "./pages/OnCall";
import { Project, Projects } from "./pages/Projects";
import Sops from "./pages/Sops";
import Tasks from "./pages/Tasks";
import Team from "./pages/Team";
import Today from "./pages/Today";

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useSession();
  if (!getToken()) return <Navigate to="/login" replace />;
  if (loading || !me) return <div className="flex h-screen items-center justify-center"><Spinner /></div>;
  return <>{children}</>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<RequireAuth><Layout /></RequireAuth>}>
            <Route index element={<Today />} />
            <Route path="feed" element={<Home />} />
            <Route path="meetings" element={<Meetings />} />
            <Route path="team" element={<Team />} />
            <Route path="tasks" element={<Tasks />} />
            <Route path="oncall" element={<OnCall />} />
            <Route path="oncall/:id" element={<OnCall />} />
            <Route path="projects" element={<Projects />} />
            <Route path="projects/:id" element={<Project />} />
            <Route path="sops" element={<Sops />} />
            <Route path="sops/:id" element={<Sops />} />
            <Route path="admin" element={<Admin />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>,
);
