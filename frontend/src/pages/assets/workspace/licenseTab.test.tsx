import { beforeEach, describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/renderApp";
import { fixtures } from "@/test/msw/fixtures";
import { AssetsWorkspace } from "../AssetsWorkspace";
import { useWorkspaceStore } from "./store";

function renderWorkspace(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/t/:tenantId/assets/*" element={<AssetsWorkspace />} />
    </Routes>,
    { route },
  );
}

beforeEach(() => {
  useWorkspaceStore.setState({ tenantId: null, tabs: [], listLocation: "", gridState: {} });
});

describe("License tab", () => {
  it("deep links to the license view and renders the normalized grid", async () => {
    renderWorkspace("/t/acme/assets/a-fw/license");
    // summary: registration account + entitlement counts
    expect(await screen.findByText("x@example.com")).toBeInTheDocument();
    expect(screen.getByText("2 active")).toBeInTheDocument();
    expect(screen.getByText("1 expired")).toBeInTheDocument();
    expect(screen.getByText("1 unknown")).toBeInTheDocument();
    // grid rows with state badges
    expect(screen.getByText("Antivirus")).toBeInTheDocument();
    const row = screen.getByText("Antivirus").closest("tr")!;
    expect(within(row).getByText("expired")).toBeInTheDocument();
    expect(within(row).getByText("AVDB")).toBeInTheDocument();
    // seats render used / max
    const vdomCell = screen.getAllByText("Vdom").find((el) => el.closest("td"))!;
    expect(within(vdomCell.closest("tr")!).getByText("1 / 10")).toBeInTheDocument();
  });

  it("filters the license grid by status", async () => {
    const user = userEvent.setup();
    renderWorkspace("/t/acme/assets/a-fw/license");
    await screen.findByText("Antivirus");

    const statusHeader = screen
      .getAllByRole("columnheader", { name: /^Status/ })
      .find((h) => !h.closest(".hidden"))!;
    await user.click(within(statusHeader).getByTitle("Filter"));
    await user.type(screen.getByPlaceholderText("value1, value2, …"), "expired{Enter}");
    await waitFor(() => expect(screen.queryByText("Web Filtering")).not.toBeInTheDocument());
    expect(screen.getByText("Antivirus")).toBeInTheDocument();
  });

  it("hides the License view tab when the asset has no license data", async () => {
    renderWorkspace("/t/acme/assets/a-plain");
    await screen.findByRole("heading", { name: "Legacy Router" });
    expect(screen.queryByRole("button", { name: "License" })).not.toBeInTheDocument();
    // a-fw does show it
    renderWorkspace("/t/acme/assets/a-fw");
    await screen.findAllByRole("heading", { name: "Branch Firewall" });
    expect(screen.getAllByRole("button", { name: "License" }).length).toBeGreaterThan(0);
  });

  it("synthesizes seat rows from license_capacity (dashboard-only consoles)", async () => {
    const con = fixtures.assets.find((a) => a.id === "a-console")!;
    con.attributes = {
      ...con.attributes,
      license_type: "Predict-Protect-and-Response",
      licenses: [
        { key: "console_license", label: "Console License", category: "platform",
          status: "active", state: "ok", expires: "2026-12-31T00:00:00",
          entitlement: null, seats: null, version: null, last_update: null,
          details: { license_type: "Predict-Protect-and-Response" } },
      ],
      license_capacity: { endpoints: { used: 4, max: 25 } },
    };
    renderWorkspace("/t/acme/assets/a-console/license");
    // appears in the summary grid AND as a synthetic table row
    expect((await screen.findAllByText("Endpoints Seats")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("4 / 25").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Console License").some((el) => el.closest("td"))).toBe(true);
  });

  it("shows the enrich hint when only raw license data exists", async () => {
    const fw = fixtures.assets.find((a) => a.id === "a-fw")!;
    fw.attributes = { ...fw.attributes, licenses: [] };
    renderWorkspace("/t/acme/assets/a-fw/license");
    expect(
      await screen.findByText("License data not normalized yet"),
    ).toBeInTheDocument();
    expect(screen.getByText(/run "Enrich now"/)).toBeInTheDocument();
  });
});
