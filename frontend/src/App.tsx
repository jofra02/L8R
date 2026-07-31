import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { GlobalShell } from "@/components/layout/GlobalShell";
import { TenantShell } from "@/components/layout/TenantShell";
import { ProtectedRoute } from "@/components/common/ProtectedRoute";
import { PostLoginRedirect } from "@/components/common/PostLoginRedirect";
import { LoginPage } from "@/pages/LoginPage";
import { ChangePasswordPage } from "@/pages/ChangePasswordPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { TicketListPage } from "@/pages/tickets/TicketListPage";
import { TicketDetailPage } from "@/pages/tickets/TicketDetailPage";
import { RunListPage } from "@/pages/runs/RunListPage";
import { AssessmentListPage } from "@/pages/assessments/AssessmentListPage";
import { AssessmentCreatePage } from "@/pages/assessments/AssessmentCreatePage";
import { AssessmentDetailPage } from "@/pages/assessments/AssessmentDetailPage";
import { RunDetailPage } from "@/pages/runs/RunDetailPage";
import { RunStatsPage } from "@/pages/runs/RunStatsPage";
import { AuditLogsPage } from "@/pages/audit/AuditLogsPage";
import { ToolCallsPage } from "@/pages/audit/ToolCallsPage";
import { ApiKeysPage } from "@/pages/settings/ApiKeysPage";
import { UsersPage } from "@/pages/settings/UsersPage";
import { ProfilesPage } from "@/pages/settings/ProfilesPage";
import { TenantDetailPage } from "@/pages/settings/TenantDetailPage";
import { InventoryPage } from "@/pages/inventory/InventoryPage";
import { AssetsPage } from "@/pages/assets/AssetsPage";
import { NotificationsPage } from "@/pages/notifications/NotificationsPage";
import { GlobalDashboardPage } from "@/pages/global/GlobalDashboardPage";
import { TenantManagementPage } from "@/pages/global/TenantManagementPage";
import { GlobalTicketsPage } from "@/pages/global/GlobalTicketsPage";
import { GlobalAssetsPage } from "@/pages/global/GlobalAssetsPage";
import { ProductCatalogPage } from "@/pages/global/ProductCatalogPage";
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
            <Route path="/change-password" element={<ChangePasswordPage />} />
            <Route path="/" element={<PostLoginRedirect />} />

            {/* Global View */}
            <Route path="/global" element={<GlobalShell />}>
              <Route index element={<ProtectedRoute permission="tenants:read"><GlobalDashboardPage /></ProtectedRoute>} />
              <Route path="tenants" element={<ProtectedRoute permission="tenants:read"><TenantManagementPage /></ProtectedRoute>} />
              <Route path="tenants/:id" element={<ProtectedRoute permission="tenants:read"><TenantDetailPage /></ProtectedRoute>} />
              <Route path="tickets" element={<ProtectedRoute permission="tickets:read"><GlobalTicketsPage /></ProtectedRoute>} />
              <Route path="assets" element={<ProtectedRoute permission="assets:read_global"><GlobalAssetsPage /></ProtectedRoute>} />
              <Route path="products" element={<ProtectedRoute permission="asset_products:manage"><ProductCatalogPage /></ProtectedRoute>} />
              <Route path="users" element={<ProtectedRoute permission="users:read"><UsersPage /></ProtectedRoute>} />
              <Route path="profiles" element={<ProtectedRoute permission="profiles:read"><ProfilesPage /></ProtectedRoute>} />
            </Route>

            {/* Tenant View */}
            <Route path="/t/:tenantId" element={<TenantShell />}>
              <Route index element={<ProtectedRoute permission="tickets:read"><DashboardPage /></ProtectedRoute>} />
              <Route path="tickets" element={<ProtectedRoute permission="tickets:read"><TicketListPage /></ProtectedRoute>} />
              <Route path="tickets/:id" element={<ProtectedRoute permission="tickets:read"><TicketDetailPage /></ProtectedRoute>} />
              <Route path="runs" element={<ProtectedRoute permission="runs:read"><RunListPage /></ProtectedRoute>} />
              <Route path="runs/stats" element={<ProtectedRoute permission="runs:read"><RunStatsPage /></ProtectedRoute>} />
              <Route path="runs/:id" element={<ProtectedRoute permission="runs:read"><RunDetailPage /></ProtectedRoute>} />
              <Route path="assessments" element={<ProtectedRoute permission="assessments:read"><AssessmentListPage /></ProtectedRoute>} />
              <Route path="assessments/new" element={<ProtectedRoute permission="assessments:write"><AssessmentCreatePage /></ProtectedRoute>} />
              <Route path="assessments/:id" element={<ProtectedRoute permission="assessments:read"><AssessmentDetailPage /></ProtectedRoute>} />
              <Route path="audit/logs" element={<ProtectedRoute permission="audit:read"><AuditLogsPage /></ProtectedRoute>} />
              <Route path="audit/tool-calls" element={<ProtectedRoute permission="audit:read"><ToolCallsPage /></ProtectedRoute>} />
              <Route path="assets/*" element={<ProtectedRoute permission="assets:read"><AssetsPage /></ProtectedRoute>} />
              <Route path="inventory" element={<ProtectedRoute permission="inventory:read"><InventoryPage /></ProtectedRoute>} />
              <Route path="notifications" element={<ProtectedRoute permission="notifications:read"><NotificationsPage /></ProtectedRoute>} />
              <Route path="settings/keys" element={<ProtectedRoute permission="keys:read"><ApiKeysPage /></ProtectedRoute>} />
              <Route path="settings/users" element={<ProtectedRoute permission="users:read"><UsersPage /></ProtectedRoute>} />
              <Route path="settings/profiles" element={<ProtectedRoute permission="profiles:read"><ProfilesPage /></ProtectedRoute>} />
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
