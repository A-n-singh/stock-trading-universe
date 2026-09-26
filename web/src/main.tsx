import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import "./index.css";
import { Loading } from "./components/ui";

const Agent = lazy(() => import("./pages/Agent"));
const Lab = lazy(() => import("./pages/Lab"));
const Markets = lazy(() => import("./pages/Markets"));
const Memory = lazy(() => import("./pages/Memory"));
const Overview = lazy(() => import("./pages/Overview"));
const Research = lazy(() => import("./pages/Research"));
const Roadmap = lazy(() => import("./pages/Roadmap"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const Trades = lazy(() => import("./pages/Trades"));

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 10_000, retry: 1 } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Layout>
          <Suspense fallback={<Loading />}>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/markets" element={<Markets />} />
            <Route path="/research" element={<Research />} />
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
    </QueryClientProvider>
  </StrictMode>,
);
