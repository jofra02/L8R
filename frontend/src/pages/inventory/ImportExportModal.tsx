import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { importInventory, getFullInventory } from "@/api/endpoints";
import type { FullInventoryResponse } from "@/api/types";

export function ImportExportModal({
  onClose,
}: {
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"export" | "import">("export");
  const [jsonText, setJsonText] = useState("");
  const [exporting, setExporting] = useState(false);

  const importMut = useMutation({
    mutationFn: importInventory,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Inventory imported successfully");
      onClose();
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Import failed"),
  });

  async function handleExport() {
    setExporting(true);
    try {
      const data: FullInventoryResponse = await getFullInventory();
      const exportData = {
        components: data.components,
        dependencies: data.dependencies,
        baselines: data.baselines,
        known_changes: data.known_changes.map(({ index: _, ...rest }) => rest),
      };
      const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `inventory-${data.customer_id}-v${data.version}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Inventory exported");
    } catch {
      toast.error("Failed to export inventory");
    } finally {
      setExporting(false);
    }
  }

  function handleImport() {
    try {
      const parsed = JSON.parse(jsonText);
      importMut.mutate({
        components: parsed.components || [],
        dependencies: parsed.dependencies || [],
        baselines: parsed.baselines || [],
        known_changes: parsed.known_changes || [],
      });
    } catch {
      toast.error("Invalid JSON");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-lg shadow-xl">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">Import / Export Inventory</h2>
        </div>
        <div className="p-5 space-y-4">
          <div className="flex gap-2">
            <button
              onClick={() => setMode("export")}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${mode === "export" ? "bg-accent text-white" : "bg-elevated text-text-secondary hover:text-text-primary"}`}
            >
              Export
            </button>
            <button
              onClick={() => setMode("import")}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${mode === "import" ? "bg-accent text-white" : "bg-elevated text-text-secondary hover:text-text-primary"}`}
            >
              Import
            </button>
          </div>

          {mode === "export" ? (
            <div className="space-y-3">
              <p className="text-sm text-text-secondary">Download the full inventory context as a JSON file.</p>
              <button
                onClick={handleExport}
                disabled={exporting}
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50"
              >
                {exporting ? "Exporting..." : "Download JSON"}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-severity-high">
                Warning: Importing replaces the entire inventory and creates a new version.
              </p>
              <textarea
                value={jsonText}
                onChange={(e) => setJsonText(e.target.value)}
                rows={10}
                className="w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-accent"
                placeholder="Paste inventory JSON here..."
              />
              <button
                onClick={handleImport}
                disabled={importMut.isPending || !jsonText.trim()}
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50"
              >
                {importMut.isPending ? "Importing..." : "Import"}
              </button>
            </div>
          )}

          <div className="flex justify-end pt-2">
            <button onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
