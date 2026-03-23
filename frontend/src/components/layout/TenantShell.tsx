import { Outlet, useNavigate, useParams } from "react-router-dom";
import { useState, useEffect, useRef } from "react";
import { TenantSidebar } from "./TenantSidebar";
import { Header } from "./Header";
import { Footer } from "./Footer";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { useAuth } from "@/hooks/useAuth";
import { TenantProvider } from "@/contexts/TenantContext";
import { setActiveTenant } from "@/api/client";
import { cn } from "@/lib/utils";

export function TenantShell() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const [collapsed, setCollapsed] = useState(false);
  const { user, logout, hasPermission, isAuthenticated, loading } = useAuth();
  const navigate = useNavigate();
  const prevTenantRef = useRef<string | null>(null);

  useEffect(() => {
    if (loading) return;
    if (!isAuthenticated) {
      navigate("/login");
      return;
    }
    if (user && !user.is_platform_admin && !user.available_tenants.includes(tenantId!)) {
      navigate("/global", { replace: true });
    }
  }, [isAuthenticated, loading, user, tenantId, navigate]);

  // Set tenant context synchronously before children render.
  // The useEffect cleanup handles clearing on unmount.
  if (tenantId && user && prevTenantRef.current !== tenantId) {
    setActiveTenant(tenantId, user.is_platform_admin);
    prevTenantRef.current = tenantId;
  }

  useEffect(() => {
    return () => {
      setActiveTenant(null, false);
      prevTenantRef.current = null;
    };
  }, []);

  // Re-set when tenantId or user changes (e.g. tenant switch)
  useEffect(() => {
    if (tenantId && user) {
      setActiveTenant(tenantId, user.is_platform_admin);
      prevTenantRef.current = tenantId;
    }
  }, [tenantId, user]);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  useEffect(() => {
    const mql = window.matchMedia("(max-width: 1024px)");
    const handler = (e: MediaQueryListEvent) => setCollapsed(e.matches);
    setCollapsed(mql.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  // Don't render children until user is loaded and tenant context is set
  if (!tenantId || !user) return <LoadingSpinner className="py-32" />;

  return (
    <TenantProvider tenantId={tenantId}>
      <div className="min-h-screen bg-background">
        <Header user={user} onLogout={handleLogout} mode="tenant" tenantId={tenantId} />
        <TenantSidebar
          collapsed={collapsed}
          onToggle={() => setCollapsed(!collapsed)}
          hasPermission={hasPermission}
          tenantId={tenantId}
        />
        <main className={cn("pt-16 pb-8 transition-all duration-200", collapsed ? "ml-16" : "ml-64")}>
          <div className="p-6">
            <Outlet />
          </div>
        </main>
        <Footer />
      </div>
    </TenantProvider>
  );
}
