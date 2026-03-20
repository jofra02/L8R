import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { AppShell } from "@/components/layout/AppShell";
import { ProtectedRoute } from "@/components/common/ProtectedRoute";
import { LoginPage } from "@/pages/LoginPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { TicketListPage } from "@/pages/tickets/TicketListPage";
import { TicketDetailPage } from "@/pages/tickets/TicketDetailPage";
import { RunListPage } from "@/pages/runs/RunListPage";
import { RunDetailPage } from "@/pages/runs/RunDetailPage";
import { RunStatsPage } from "@/pages/runs/RunStatsPage";
import { AuditLogsPage } from "@/pages/audit/AuditLogsPage";
import { ToolCallsPage } from "@/pages/audit/ToolCallsPage";
import { ApiKeysPage } from "@/pages/settings/ApiKeysPage";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<AppShell />}>
              <Route
                path="/"
                element={
                  <ProtectedRoute minRole="operator">
                    <DashboardPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/tickets"
                element={
                  <ProtectedRoute minRole="operator">
                    <TicketListPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/tickets/:id"
                element={
                  <ProtectedRoute minRole="operator">
                    <TicketDetailPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/runs"
                element={
                  <ProtectedRoute minRole="operator">
                    <RunListPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/runs/stats"
                element={
                  <ProtectedRoute minRole="operator">
                    <RunStatsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/runs/:id"
                element={
                  <ProtectedRoute minRole="operator">
                    <RunDetailPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/audit/logs"
                element={
                  <ProtectedRoute minRole="viewer">
                    <AuditLogsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/audit/tool-calls"
                element={
                  <ProtectedRoute minRole="viewer">
                    <ToolCallsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/settings/keys"
                element={
                  <ProtectedRoute minRole="tenant_admin">
                    <ApiKeysPage />
                  </ProtectedRoute>
                }
              />
            </Route>
          </Routes>
        </BrowserRouter>
        <Toaster
          theme="dark"
          position="bottom-right"
          toastOptions={{
            style: {
              background: "#161b22",
              border: "1px solid #30363d",
              color: "#e6edf3",
            },
          }}
        />
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
