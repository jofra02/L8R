import { beforeEach, describe, expect, it } from "vitest";
import { Route, Routes, useLocation } from "react-router-dom";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/renderApp";
import { AssetsWorkspace } from "../AssetsWorkspace";
import { useWorkspaceStore } from "./store";

function LocationProbe() {
  const location = useLocation();
  return (
    <div>
      <span data-testid="path">{location.pathname}</span>
      <span data-testid="search">{location.search}</span>
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

async function drillIntoDc1(user: ReturnType<typeof userEvent.setup>) {
  renderWorkspace("/t/acme/assets/a-console/sub-inventory");
  // root-level children of the console: DC1 + WS2, interfaces not listed
  await screen.findByText("DC1");
  expect(screen.getByText("WS2")).toBeInTheDocument();
  expect(screen.queryByText("eth0")).not.toBeInTheDocument();
  await user.click(screen.getByText("DC1"));
  await screen.findByRole("heading", { name: "DC1" });
}

describe("subitem drill-down", () => {
  it("drills asset → child → grandchild with the same shell", async () => {
    const user = userEvent.setup();
    await drillIntoDc1(user);

    expect(path()).toBe("/t/acme/assets/a-console/sub/ep-dc1");
    // breadcrumb: Assets / FortiEDR Console / Discovered inventory / DC1
    expect(screen.getByRole("link", { name: "Assets" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "FortiEDR Console" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Discovered inventory" })).toBeInTheDocument();

    // capability-driven views: DC1 has children → Discovered inventory tab exists
    await user.click(screen.getByRole("button", { name: "Discovered inventory" }));
    expect(path()).toBe("/t/acme/assets/a-console/sub/ep-dc1/sub-inventory");
    await screen.findByText("eth0");
    expect(screen.getByText("eth1")).toBeInTheDocument();

    // grandchild: same shell again
    await user.click(screen.getByText("eth0"));
    await screen.findByRole("heading", { name: "eth0" });
    expect(path()).toBe("/t/acme/assets/a-console/sub/if-dc1-1");
    // eth0 has no children → no Discovered inventory view tab
    expect(screen.queryByRole("button", { name: "Discovered inventory" })).not.toBeInTheDocument();
    // but it has attributes → Attributes tab present
    expect(screen.getByRole("button", { name: "Attributes" })).toBeInTheDocument();
    // still ONE workspace tab (drill-down reuses it)
    expect(search()).toContain("tabs=a-console");
    expect(search()).not.toContain("%2C");
  });

  it("navigates back through the breadcrumb parent chain", async () => {
    const user = userEvent.setup();
    await drillIntoDc1(user);
    await user.click(screen.getByRole("button", { name: "Discovered inventory" }));
    await screen.findByText("eth0");
    await user.click(screen.getByText("eth0"));
    await screen.findByRole("heading", { name: "eth0" });

    // breadcrumb chain includes DC1; clicking returns to its shell
    await user.click(screen.getByRole("link", { name: "DC1" }));
    await screen.findByRole("heading", { name: "DC1" });
    expect(path()).toBe("/t/acme/assets/a-console/sub/ep-dc1");
  });

  it("deep links to a grandchild and rebuilds the ancestor breadcrumb", async () => {
    renderWorkspace("/t/acme/assets/a-console/sub/if-dc1-1");
    await screen.findByRole("heading", { name: "eth0" });
    // ancestors from the API: Assets / FortiEDR Console / Discovered inventory / DC1 / Discovered inventory
    expect(await screen.findByRole("link", { name: "DC1" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "FortiEDR Console" })).toBeInTheDocument();
    await waitFor(() => expect(search()).toContain("tabs=a-console"));
  });

  it("opens a subitem in its own workspace tab from the context menu", async () => {
    const user = userEvent.setup();
    await drillIntoDc1(user);
    // back to the asset's sub-inventory to use the row context menu
    await user.click(screen.getByRole("link", { name: "Discovered inventory" }));
    const row = (await screen.findByText("WS2")).closest("tr")!;
    fireEvent.contextMenu(row);
    await user.click(await screen.findByText("Open in new tab"));

    await screen.findByRole("heading", { name: "WS2" });
    expect(path()).toBe("/t/acme/assets/a-console/sub/ep-ws2");
    expect(decodeURIComponent(search())).toContain("a-console.ep-ws2");
    expect(document.querySelector('[data-tab-id="a-console.ep-ws2"]')).not.toBeNull();
    // original asset tab still open alongside
    expect(document.querySelector('[data-tab-id="a-console"]')).not.toBeNull();
  });

  it("keeps children grid filters when returning through the breadcrumb", async () => {
    const user = userEvent.setup();
    await drillIntoDc1(user);
    await user.click(screen.getByRole("button", { name: "Discovered inventory" }));
    await screen.findByText("eth0");

    // filter the children grid by name (kept-mounted hidden panels also
    // contain a Name header — take the one in the visible panel)
    const nameHeader = screen
      .getAllByRole("columnheader", { name: /^Name/ })
      .find((h) => !h.closest(".hidden"))!;
    await user.click(nameHeader.querySelector('[title="Filter"]') as HTMLElement);
    await user.type(screen.getByPlaceholderText("value1, value2, …"), "eth0{Enter}");
    await waitFor(() => expect(search()).toContain("f.name=eth0"));
    await waitFor(() => expect(screen.queryByText("eth1")).not.toBeInTheDocument());

    // drill into eth0 and come back via breadcrumb → filter restored
    const rowCell = screen.getAllByText("eth0").find((el) => el.closest("td"))!;
    await user.click(rowCell);
    await screen.findByRole("heading", { name: "eth0" });
    await user.click(screen.getAllByRole("link", { name: "Discovered inventory" }).pop() as HTMLElement);
    await waitFor(() =>
      expect(screen.getAllByText("eth0").some((el) => el.closest("td"))).toBe(true),
    );
    expect(screen.queryByText("eth1")).not.toBeInTheDocument();
    // active filter chip visible again
    expect(screen.getAllByText("eth0").some((el) => !el.closest("td"))).toBe(true);
  });
});
