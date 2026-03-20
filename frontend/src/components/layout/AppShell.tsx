import { Outlet, useNavigate } from "react-router-dom";
import { useState, useEffect } from "react";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { Footer } from "./Footer";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

export function AppShell() {
  const [collapsed, setCollapsed] = useState(false);
  const { context, logout, hasRole, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!isAuthenticated) {
      navigate("/login");
    }
  }, [isAuthenticated, navigate]);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  // Auto-collapse on small screens
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 1024px)");
    const handler = (e: MediaQueryListEvent) => setCollapsed(e.matches);
    setCollapsed(mql.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return (
    <div className="min-h-screen bg-background">
      <Header auth={context} onLogout={handleLogout} />
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} hasRole={hasRole} />
      <main
        className={cn(
          "pt-16 pb-8 transition-all duration-200",
          collapsed ? "ml-16" : "ml-64",
        )}
      >
        <div className="p-6">
          <Outlet />
        </div>
      </main>
      <Footer />
    </div>
  );
}
