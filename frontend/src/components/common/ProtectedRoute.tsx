import { Navigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

interface ProtectedRouteProps {
  permission?: string;
  children: React.ReactNode;
}

export function ProtectedRoute({ permission, children }: ProtectedRouteProps) {
  const { isAuthenticated, hasPermission, loading, user } = useAuth();

  if (loading) return null;

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (user?.must_change_password) {
    return <Navigate to="/change-password" replace />;
  }

  if (permission && !hasPermission(permission)) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-text-secondary">Insufficient permissions. Requires <code className="text-text-primary">{permission}</code>.</p>
      </div>
    );
  }

  return <>{children}</>;
}
