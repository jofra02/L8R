import type { ReactElement, ReactNode } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TenantProvider } from "@/contexts/TenantContext";

export const DEFAULT_PERMISSIONS = [
  "assets:read",
  "assets:write",
  "assets:manage",
];

/** useAuth reads localStorage directly (no provider) — seeding these keys is
 * the whole auth stub. */
export function seedAuth(permissions: string[] = DEFAULT_PERMISSIONS): void {
  localStorage.setItem("access_token", "test-token");
  localStorage.setItem(
    "auth_user",
    JSON.stringify({
      id: "u-test",
      email: "test@example.com",
      display_name: "Test User",
      is_platform_admin: false,
      customer_id: "acme",
      available_tenants: ["acme"],
      permissions,
      must_change_password: false,
    }),
  );
}

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

interface RenderOptions {
  route?: string;
  tenantId?: string;
  permissions?: string[];
  queryClient?: QueryClient;
  /** Wrap the UI yourself (e.g. with <Routes>); receives the tenant-wrapped children. */
  wrapper?: (children: ReactNode) => ReactElement;
}

export function renderWithProviders(ui: ReactElement, options: RenderOptions = {}) {
  const {
    route = "/t/acme/assets",
    tenantId = "acme",
    permissions = DEFAULT_PERMISSIONS,
    queryClient = createTestQueryClient(),
    wrapper,
  } = options;

  seedAuth(permissions);

  const inner = <TenantProvider tenantId={tenantId}>{ui}</TenantProvider>;
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{wrapper ? wrapper(inner) : inner}</MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}
