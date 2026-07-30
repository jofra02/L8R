import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { importAssets } from "@/api/endpoints";
import type { AssetImportResponse } from "@/api/types";

const inputClass =
  "w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent";

const MATCH_KEYS = ["id", "ref", "serial_number", "external_id"];

export function ImportModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [matchKey, setMatchKey] = useState("id");
  const [fileName, setFileName] = useState("");
  const [payload, setPayload] = useState<string | { assets: Record<string, unknown>[] } | null>(null);
  const [preview, setPreview] = useState<AssetImportResponse | null>(null);
  const [busy, setBusy] = useState(false);

  const handleFile = (file: File) => {
    setFileName(file.name);
    setPreview(null);
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? "");
      if (file.name.toLowerCase().endsWith(".csv")) {
        setPayload(text);
      } else {
        try {
          const parsed = JSON.parse(text);
          setPayload(Array.isArray(parsed) ? { assets: parsed } : parsed);
        } catch {
          toast.error("Invalid JSON file");
          setPayload(null);
        }
      }
    };
    reader.readAsText(file);
  };

  const run = async (dryRun: boolean) => {
    if (!payload) return toast.error("Choose a CSV or JSON file first");
    setBusy(true);
    try {
      const result = await importAssets(payload, { dryRun, matchKey });
      if (dryRun) {
        setPreview(result);
      } else {
        toast.success(`Import done: ${result.created} created, ${result.updated} updated, ${result.failed} failed`);
        queryClient.invalidateQueries({ queryKey: ["assets"] });
        queryClient.invalidateQueries({ queryKey: ["inventory"] });
        onClose();
      }
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Import failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-2xl shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">Import Assets</h2>
          <p className="text-xs text-text-muted mt-1">
            CSV (columns: name, ref, asset_type, serial_number, attr.&lt;key&gt;, ...) or JSON.
            Non-destructive upsert — assets absent from the file are never deleted.
          </p>
        </div>
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-text-secondary mb-1">File</label>
              <input
                type="file"
                accept=".csv,.json"
                onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
                className={inputClass}
              />
              {fileName && <p className="text-xs text-text-muted mt-1">{fileName}</p>}
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Match existing assets by</label>
              <select value={matchKey} onChange={(e) => setMatchKey(e.target.value)} className={inputClass}>
                {MATCH_KEYS.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </div>
          </div>

          {preview && (
            <div className="space-y-2">
              <p className="text-sm text-text-primary">
                Dry run: {preview.created} to create, {preview.updated} to update, {preview.failed} with errors
              </p>
              {preview.rows.filter((r) => r.action === "error").length > 0 && (
                <div className="border border-status-failed/30 bg-status-failed/10 rounded-md p-3 max-h-48 overflow-y-auto">
                  {preview.rows.filter((r) => r.action === "error").map((r) => (
                    <p key={r.row} className="text-xs text-status-failed">
                      Row {r.row}: {r.errors.join("; ")}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
              Cancel
            </button>
            <button
              onClick={() => run(true)}
              disabled={busy || !payload}
              className="px-4 py-2 bg-elevated border border-border text-text-secondary hover:text-text-primary text-sm rounded-md transition-colors disabled:opacity-50"
            >
              {busy ? "Validating..." : "Dry run"}
            </button>
            <button
              onClick={() => run(false)}
              disabled={busy || !payload || !preview || preview.failed === preview.total}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50"
              title={!preview ? "Run a dry run first" : undefined}
            >
              {busy ? "Importing..." : "Import"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
