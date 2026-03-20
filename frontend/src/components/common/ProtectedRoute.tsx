import { Navigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

interface ProtectedRouteProps {
  minRole?: string;
  children: React.ReactNode;
}

export function ProtectedRoute({ minRole = "viewer", children }: ProtectedRouteProps) {
  const { isAuthenticated, hasRole, loading } = useAuth();

  if (loading) return null;

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (!hasRole(minRole)) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-text-secondary">Insufficient permissions. Requires {minRole} role or higher.</p>
      </div>
    );
  }

  return <>{children}</>;
}
