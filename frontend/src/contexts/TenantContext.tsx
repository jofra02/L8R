import { createContext, useContext } from "react";

interface TenantContextValue {
  tenantId: string;
}

const TenantContext = createContext<TenantContextValue | null>(null);

export function TenantProvider({ tenantId, children }: { tenantId: string; children: React.ReactNode }) {
  return <TenantContext.Provider value={{ tenantId }}>{children}</TenantContext.Provider>;
}

export function useTenantId(): string {
  const ctx = useContext(TenantContext);
  if (!ctx) throw new Error("useTenantId must be used within a TenantProvider");
  return ctx.tenantId;
}

/** Tenant id when inside a tenant shell, null on global pages. */
export function useOptionalTenantId(): string | null {
  return useContext(TenantContext)?.tenantId ?? null;
}
