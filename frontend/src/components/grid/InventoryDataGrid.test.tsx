import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InventoryDataGrid } from "./InventoryDataGrid";
import { DEFAULT_GRID_STATE, type GridColumnSchema, type GridState } from "./types";

interface Row {
  id: string;
  name: string;
  state: string;
  meta: Record<string, unknown> | null;
}

const rows: Row[] = Array.from({ length: 30 }, (_, i) => ({
  id: `r${i}`,
  name: i === 0 ? "alpha" : i === 1 ? "beta" : `row-${String(i).padStart(2, "0")}`,
  state: i % 2 === 0 ? "Up" : "Down",
  meta: i === 0 ? { nested: { deep: true }, count: 3 } : null,
}));

const columns: GridColumnSchema<Row>[] = [
  { key: "name", header: "Name", type: "link", sortable: true, filterable: true, primary: true },
  { key: "state", header: "State", type: "badge", sortable: true, filterable: true },
  { key: "meta", header: "Meta", type: "complex" },
];

function Harness({
  onOpen,
  onSelectSpy,
  initial,
}: {
  onOpen?: (row: Row) => void;
  onSelectSpy?: (row: Row | null) => void;
  initial?: Partial<GridState>;
}) {
  const [state, setState] = useState<GridState>({
    ...DEFAULT_GRID_STATE,
    pageSize: 10,
    ...initial,
  });
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <InventoryDataGrid<Row>
      gridId="test.grid"
      columns={columns}
      data={rows}
      mode="client"
      state={state}
      onStateChange={setState}
      getRowId={(r) => r.id}
      selectedRowId={selected}
      onSelect={(r) => {
        setSelected(r ? r.id : null);
        onSelectSpy?.(r);
      }}
      onOpen={onOpen}
      contextMenuItems={(r) => [{ label: `Ctx ${r.name}`, onSelect: () => {} }]}
    />
  );
}

describe("InventoryDataGrid (client mode)", () => {
  it("paginates client-side and reports the row count", () => {
    render(<Harness />);
    expect(screen.getByText("30 rows")).toBeInTheDocument();
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    expect(screen.queryByText("row-15")).not.toBeInTheDocument();
  });

  it("filters through the column popover with comma-separated tokens", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const nameHeader = screen.getByText("Name").closest("th")!;
    await user.click(within(nameHeader).getByTitle("Filter"));
    const input = screen.getByPlaceholderText("value1, value2, …");
    await user.type(input, "alpha, beta{Enter}");
    expect(screen.getByText("2 / 30 rows")).toBeInTheDocument();
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
    expect(screen.queryByText("row-02")).not.toBeInTheDocument();
    // chips row reflects the active filter
    expect(screen.getByText("alpha, beta")).toBeInTheDocument();
  });

  it("keeps the header and shows a hint when filters match nothing", async () => {
    const user = userEvent.setup();
    render(<Harness initial={{ filters: { name: ["zzz-nothing"] } }} />);
    expect(screen.getByText("No rows match the active filters")).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    await user.click(screen.getByText("Clear all"));
    expect(screen.getByText("alpha")).toBeInTheDocument();
  });

  it("sorts on header click and toggles direction", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByText("Name"));
    let cells = screen.getAllByRole("row").slice(1);
    expect(within(cells[0]!).getByText("alpha")).toBeInTheDocument();
    await user.click(screen.getByText("Name"));
    cells = screen.getAllByRole("row").slice(1);
    expect(within(cells[0]!).getByText("row-29")).toBeInTheDocument();
  });

  it("supports keyboard selection and Enter-to-open", async () => {
    const onOpen = vi.fn();
    const onSelectSpy = vi.fn();
    render(<Harness onOpen={onOpen} onSelectSpy={onSelectSpy} />);
    const container = screen.getByText("alpha").closest("div[tabindex]")!;
    fireEvent.keyDown(container, { key: "ArrowDown" });
    expect(onSelectSpy).toHaveBeenLastCalledWith(expect.objectContaining({ id: "r0" }));
    fireEvent.keyDown(container, { key: "ArrowDown" });
    expect(onSelectSpy).toHaveBeenLastCalledWith(expect.objectContaining({ id: "r1" }));
    fireEvent.keyDown(container, { key: "Enter" });
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "r1" }));
  });

  it("opens the resource from the primary cell and by double click", async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(<Harness onOpen={onOpen} />);
    await user.click(screen.getByText("alpha"));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "r0" }));
    await user.dblClick(screen.getByText("beta"));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "r1" }));
  });

  it("shows a context menu on right click", () => {
    render(<Harness />);
    fireEvent.contextMenu(screen.getByText("alpha").closest("tr")!);
    expect(screen.getByText("Ctx alpha")).toBeInTheDocument();
  });

  it("renders complex values as a summary that opens the inspector drawer", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const inspectBtn = screen.getByTitle("Inspect value");
    expect(inspectBtn).toHaveTextContent("count: 3");
    await user.click(inspectBtn);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByText(/"nested"/)).toBeInTheDocument();
  });

  it("toggles column visibility from the Columns menu", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getByRole("columnheader", { name: /State/i })).toBeInTheDocument();
    await user.click(screen.getByTitle("Columns"));
    await user.click(screen.getByRole("checkbox", { name: /State/i }));
    expect(screen.queryByRole("columnheader", { name: /State/i })).not.toBeInTheDocument();
  });
});
