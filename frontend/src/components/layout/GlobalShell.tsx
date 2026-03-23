import { Outlet, useNavigate } from "react-router-dom";
import { useState, useEffect } from "react";
import { GlobalSidebar } from "./GlobalSidebar";
import { Header } from "./Header";
import { Footer } from "./Footer";
import { useAuth } from "@/hooks/useAuth";
import { setActiveTenant } from "@/api/client";
import { cn } from "@/lib/utils";

export function GlobalShell() {
  const [collapsed, setCollapsed] = useState(false);
  const { user, logout, hasPermission, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!isAuthenticated) navigate("/login");
  }, [isAuthenticated, navigate]);

  // Clear tenant context when entering global view
  useEffect(() => {
    setActiveTenant(null, false);
  }, []);

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

  return (
    <div className="min-h-screen bg-background">
      <Header user={user} onLogout={handleLogout} mode="global" />
      <GlobalSidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} hasPermission={hasPermission} />
      <main className={cn("pt-16 pb-8 transition-all duration-200", collapsed ? "ml-16" : "ml-64")}>
        <div className="p-6">
          <Outlet />
        </div>
      </main>
      <Footer />
    </div>
  );
}
