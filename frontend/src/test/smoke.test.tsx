import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { useAssets } from "@/hooks/useAssets";
import { useTenantId } from "@/contexts/TenantContext";
import { renderWithProviders } from "./renderApp";

function TenantProbe() {
  const tenantId = useTenantId();
  return <div>tenant:{tenantId}</div>;
}

function AssetNames() {
  const { data, isLoading } = useAssets({ page: 1, page_size: 25 });
  if (isLoading) return <div>loading</div>;
  return (
    <ul>
      {data?.items.map((a) => (
        <li key={a.id}>{a.name}</li>
      ))}
    </ul>
  );
}

describe("test infrastructure", () => {
  it("renders with router, query client and tenant provider", () => {
    renderWithProviders(<TenantProbe />);
    expect(screen.getByText("tenant:acme")).toBeInTheDocument();
  });

  it("round-trips the axios client through msw fixtures", async () => {
    renderWithProviders(<AssetNames />);
    expect(await screen.findByText("FortiEDR Console")).toBeInTheDocument();
    expect(screen.getByText("Branch Firewall")).toBeInTheDocument();
  });
});
