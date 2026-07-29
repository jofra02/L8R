import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowUpDown, Boxes } from "lucide-react";
import { getFullInventory } from "@/api/endpoints";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { useAuth } from "@/hooks/useAuth";
import { BaselinesTab } from "./BaselinesTab";
import { KnownChangesTab } from "./KnownChangesTab";
import { ImportExportModal } from "./ImportExportModal";

// Components/Dependencies moved to the Assets module (/t/:tenantId/assets);
// this page keeps the blob-owned baselines and known changes.
type Tab = "baselines" | "changes";

const TABS: { key: Tab; label: string }[] = [
  { key: "baselines", label: "Baselines" },
  { key: "changes", label: "Known Changes" },
];

export function InventoryPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const { hasPermission } = useAuth();
  const canWrite = hasPermission("inventory:write");
  const [tab, setTab] = useState<Tab>("baselines");
  const [importExportOpen, setImportExportOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["inventory", "full"],
    queryFn: getFullInventory,
  });

  if (isLoading) return <LoadingSpinner className="py-16" />;

  const components = data?.components ?? [];
  const dependencies = data?.dependencies ?? [];
  const baselines = data?.baselines ?? [];
  const knownChanges = data?.known_changes ?? [];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-text-primary">Inventory</h1>
          {data && (
            <span className="text-xs bg-elevated border border-border rounded px-2 py-0.5 text-text-muted">
              v{data.version}
            </span>
          )}
        </div>
        {canWrite && (
          <button
            onClick={() => setImportExportOpen(true)}
            className="flex items-center gap-2 bg-elevated border border-border hover:bg-card text-text-secondary text-sm px-4 py-2 rounded-md transition-colors"
          >
            <ArrowUpDown size={16} /> Import / Export
          </button>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Components", value: components.length },
          { label: "Dependencies", value: dependencies.length },
          { label: "Baselines", value: baselines.length },
          { label: "Known Changes", value: knownChanges.length },
        ].map((s) => (
          <div key={s.label} className="bg-card border border-border rounded-lg px-4 py-3">
            <p className="text-xs text-text-muted">{s.label}</p>
            <p className="text-xl font-semibold text-text-primary">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Components/Dependencies now live in Assets */}
      <div className="bg-card border border-border rounded-lg px-4 py-3 flex items-center justify-between">
        <p className="text-sm text-text-secondary">
          Components and dependencies are managed in the Assets module.
        </p>
        <Link
          to={`/t/${tenantId}/assets`}
          className="flex items-center gap-2 text-sm text-accent hover:underline"
        >
          <Boxes size={16} /> Open Assets
        </Link>
      </div>

      {/* Tabs */}
      <div className="border-b border-border flex gap-0">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab === t.key
                ? "border-accent text-text-primary"
                : "border-transparent text-text-muted hover:text-text-secondary"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "baselines" && <BaselinesTab baselines={baselines} components={components} canWrite={canWrite} />}
      {tab === "changes" && <KnownChangesTab knownChanges={knownChanges} components={components} canWrite={canWrite} />}

      {importExportOpen && <ImportExportModal onClose={() => setImportExportOpen(false)} />}
    </div>
  );
}
