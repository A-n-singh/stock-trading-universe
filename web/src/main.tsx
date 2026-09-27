import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthRequired, setAuthHandler, useAuth } from "./api";
import { Layout } from "./components/Layout";
import "./index.css";
import { Loading } from "./components/ui";

const Agent = lazy(() => import("./pages/Agent"));
const Agents = lazy(() => import("./pages/Agents"));
const Lab = lazy(() => import("./pages/Lab"));
const Markets = lazy(() => import("./pages/Markets"));
const Memory = lazy(() => import("./pages/Memory"));
const Overview = lazy(() => import("./pages/Overview"));
const Research = lazy(() => import("./pages/Research"));
const Roadmap = lazy(() => import("./pages/Roadmap"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const Trades = lazy(() => import("./pages/Trades"));
const Login = lazy(() => import("./pages/Login"));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: (n, err) => !(err instanceof AuthRequired) && n < 1 } },
});
// Any "login required" answer (e.g. the session expired) sends the user back to the login screen.
setAuthHandler(() => queryClient.setQueryData(["auth"], { required: true, logged_in: false }));

function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  if (auth.isLoading) return <Loading />;
  if (auth.data?.required && !auth.data.logged_in) return <Suspense fallback={<Loading />}><Login /></Suspense>;
  return <>{children}</>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthGate>
      <BrowserRouter>
        <Layout>
          <Suspense fallback={<Loading />}>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/markets" element={<Markets />} />
            <Route path="/research" element={<Research />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/agent" element={<Agent />} />
            <Route path="/lab" element={<Lab />} />
            <Route path="/trades" element={<Trades />} />
            <Route path="/memory" element={<Memory />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/roadmap" element={<Roadmap />} />
          </Routes>
          </Suspense>
        </Layout>
      </BrowserRouter>
      </AuthGate>
    </QueryClientProvider>
  </StrictMode>,
);
