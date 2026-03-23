import { useNavigate } from "react-router-dom";
import { useCallback } from "react";
import { useTenantId } from "@/contexts/TenantContext";

export function useTenantNavigate() {
  const navigate = useNavigate();
  const tenantId = useTenantId();

  return useCallback(
    (path: string, options?: { replace?: boolean; state?: unknown }) => {
      navigate(`/t/${tenantId}${path}`, options);
    },
    [navigate, tenantId],
  );
}
