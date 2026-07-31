import { beforeEach, describe, expect, it } from "vitest";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/renderApp";
import { AssetsWorkspace } from "../AssetsWorkspace";
import { useWorkspaceStore } from "./store";

function LocationProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <div>
      <span data-testid="path">{location.pathname}</span>
      <span data-testid="search">{location.search}</span>
      <button onClick={() => navigate(-1)}>test-back</button>
    </div>
  );
}

function renderWorkspace(route = "/t/acme/assets") {
  return renderWithProviders(
    <>
      <Routes>
        <Route path="/t/:tenantId/assets/*" element={<AssetsWorkspace />} />
      </Routes>
      <LocationProbe />
    </>,
    { route },
  );
}

const path = () => screen.getByTestId("path").textContent ?? "";
const search = () => screen.getByTestId("search").textContent ?? "";

beforeEach(() => {
  useWorkspaceStore.setState({ tenantId: null, tabs: [], listLocation: "", gridState: {} });
});

describe("AssetsWorkspace", () => {
  it("opens an asset as a workspace tab and updates the URL", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(await screen.findByText("Branch Firewall"));

    expect(path()).toBe("/t/acme/assets/a-fw");
    expect(search()).toContain("tabs=a-fw");
    // tab strip: master list tab + the asset tab
    expect(document.querySelector('[data-tab-id="__list"]')).not.toBeNull();
    expect(document.querySelector('[data-tab-id="a-fw"]')).not.toBeNull();
    // shell renders breadcrumb + view tabs
    expect(await screen.findByRole("heading", { name: "Branch Firewall" })).toBeInTheDocument();
    expect(screen.getByText("Attributes")).toBeInTheDocument();
  });

  it("switches views within the same tab (no new workspace tab)", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(await screen.findByText("Branch Firewall"));
    await screen.findByRole("heading", { name: "Branch Firewall" });

    await user.click(screen.getByText("Attributes"));
    expect(path()).toBe("/t/acme/assets/a-fw/attributes");
    // still exactly one asset tab open
    expect(search()).toContain("tabs=a-fw");
    expect(search()).not.toContain("%2C"); // no comma → single token
    // attributes content renders (os_version from fixtures)
    expect(await screen.findByText("7.4.5")).toBeInTheDocument();
  });

  it("returns to a state-preserving list via the breadcrumb", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(await screen.findByText("Branch Firewall"));
    await screen.findByRole("heading", { name: "Branch Firewall" });

    await user.click(screen.getByRole("link", { name: "Assets" }));
    expect(path()).toBe("/t/acme/assets");
    // tab stays open, list visible again
    expect(search()).toContain("tabs=a-fw");
    expect(await screen.findByText("FortiEDR Console")).toBeInTheDocument();
  });

  it("browser back restores the previous location", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(await screen.findByText("Branch Firewall"));
    await screen.findByRole("heading", { name: "Branch Firewall" });
    await user.click(screen.getByText("Attributes"));
    expect(path()).toBe("/t/acme/assets/a-fw/attributes");

    await user.click(screen.getByText("test-back"));
    expect(path()).toBe("/t/acme/assets/a-fw");

    await user.click(screen.getByText("test-back"));
    expect(path()).toBe("/t/acme/assets");
    expect(await screen.findByText("FortiEDR Console")).toBeInTheDocument();
  });

  it("deep links to an asset view and registers the tab", async () => {
    renderWorkspace("/t/acme/assets/a-fw/attributes");
    expect(await screen.findByRole("heading", { name: "Branch Firewall" })).toBeInTheDocument();
    expect(await screen.findByText("7.4.5")).toBeInTheDocument();
    await waitFor(() => expect(search()).toContain("tabs=a-fw"));
    expect(useWorkspaceStore.getState().tabs.map((t) => t.token)).toEqual(["a-fw"]);
  });

  it("closing the active tab falls back to the master list", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(await screen.findByText("Branch Firewall"));
    await screen.findByRole("heading", { name: "Branch Firewall" });

    await user.click(screen.getByTitle("Close tab"));
    expect(path()).toBe("/t/acme/assets");
    expect(search()).not.toContain("tabs=");
    expect(await screen.findByText("FortiEDR Console")).toBeInTheDocument();
  });

  it("preserves list grid state in the URL and across tab switches", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText("Branch Firewall");

    // filter the Name column via the popover
    const nameHeader = screen.getByRole("columnheader", { name: /^Name/ });
    await user.click(within(nameHeader).getByTitle("Filter"));
    await user.type(screen.getByPlaceholderText("value1, value2, …"), "Branch{Enter}");
    await waitFor(() => expect(search()).toContain("f.name=Branch"));

    // open an asset, then come back through the Assets tab
    await user.click(await screen.findByText("Branch Firewall"));
    await screen.findByRole("heading", { name: "Branch Firewall" });
    await user.click(document.querySelector('[data-tab-id="__list"]') as HTMLElement);
    await waitFor(() => expect(path()).toBe("/t/acme/assets"));
    // the filter chip survived the round-trip
    expect(search()).toContain("f.name=Branch");
    expect(screen.getByText("Branch")).toBeInTheDocument();
  });

  it("wipes tabs when the tenant changes", async () => {
    const user = userEvent.setup();
    const first = renderWorkspace();
    await user.click(await screen.findByText("Branch Firewall"));
    await screen.findByRole("heading", { name: "Branch Firewall" });
    expect(useWorkspaceStore.getState().tabs).toHaveLength(1);
    first.unmount();

    renderWithProviders(
      <Routes>
        <Route path="/t/:tenantId/assets/*" element={<AssetsWorkspace />} />
      </Routes>,
      { route: "/t/other/assets", tenantId: "other" },
    );
    await waitFor(() => expect(useWorkspaceStore.getState().tenantId).toBe("other"));
    expect(useWorkspaceStore.getState().tabs).toHaveLength(0);
  });
});
