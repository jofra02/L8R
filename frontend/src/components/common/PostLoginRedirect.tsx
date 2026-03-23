import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { LoadingSpinner } from "./LoadingSpinner";

export function PostLoginRedirect() {
  const { user, isAuthenticated, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (loading) return;
    if (!isAuthenticated || !user) {
      navigate("/login", { replace: true });
      return;
    }

    if (user.is_platform_admin || user.available_tenants.length > 1) {
      navigate("/global", { replace: true });
    } else if (user.available_tenants.length === 1) {
      navigate(`/t/${user.available_tenants[0]}`, { replace: true });
    } else {
      navigate("/global", { replace: true });
    }
  }, [user, isAuthenticated, loading, navigate]);

  return <LoadingSpinner className="py-32" />;
}
