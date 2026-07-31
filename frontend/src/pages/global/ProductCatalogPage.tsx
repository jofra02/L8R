import { useState } from "react";
import { Package, Pencil, Plus, Trash2 } from "lucide-react";
import { DataTable, type Column } from "@/components/common/DataTable";
import { TimeAgo } from "@/components/common/TimeAgo";
import {
  useAssetProducts,
  useCreateAssetProduct,
  useDeleteAssetProduct,
  useRenameAssetProduct,
} from "@/hooks/useAssets";
import type { AssetProduct } from "@/api/types";

const inputClass =
  "w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent";

function ProductModal({
  editing,
  onClose,
}: {
  editing?: AssetProduct;
  onClose: () => void;
}) {
  const [name, setName] = useState(editing?.name ?? "");
  const createMutation = useCreateAssetProduct();
  const renameMutation = useRenameAssetProduct();
  const isPending = createMutation.isPending || renameMutation.isPending;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    if (editing) {
      renameMutation.mutate({ id: editing.id, name: trimmed }, { onSuccess: onClose });
    } else {
      createMutation.mutate(trimmed, { onSuccess: onClose });
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-md shadow-xl">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">
            {editing ? "Rename product" : "Add product"}
          </h2>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className="block text-xs text-text-secondary mb-1">Product name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder='e.g. "FortiGate", "ESXi", "Veeam Backup & Replication"'
              autoFocus
              className={inputClass}
            />
          </div>
          {editing && (
            <p className="text-xs text-severity-medium">
              Renaming propagates to all assets referencing this product, across all tenants.
            </p>
          )}
          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending || !name.trim()}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50"
            >
              {isPending ? "Saving..." : editing ? "Rename" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function ProductCatalogPage() {
  const { data: products, isLoading } = useAssetProducts(true);
  const deleteMutation = useDeleteAssetProduct();
  const [modal, setModal] = useState<{ open: boolean; editing?: AssetProduct }>({ open: false });
  const [deleting, setDeleting] = useState<AssetProduct | null>(null);

  const columns: Column<AssetProduct>[] = [
    {
      key: "name",
      header: "Name",
      render: (r) => <span className="text-text-primary font-medium">{r.name}</span>,
    },
    {
      key: "usage_count",
      header: "In use",
      render: (r) => (
        <span className="text-xs text-text-secondary">
          {r.usage_count ? `${r.usage_count} asset${r.usage_count === 1 ? "" : "s"}` : "—"}
        </span>
      ),
      className: "w-32",
    },
    {
      key: "created_at",
      header: "Created",
      render: (r) => <TimeAgo date={r.created_at} />,
      className: "w-32",
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div className="flex items-center justify-end gap-1">
          <button
            onClick={(e) => { e.stopPropagation(); setModal({ open: true, editing: r }); }}
            title="Rename"
            className="p-1.5 rounded text-text-muted hover:text-text-primary hover:bg-elevated"
          >
            <Pencil size={14} />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setDeleting(r); }}
            disabled={!!r.usage_count}
            title={r.usage_count ? "In use — reassign the assets first" : "Delete"}
            className="p-1.5 rounded text-text-muted hover:text-status-failed hover:bg-elevated disabled:opacity-30 disabled:hover:text-text-muted"
          >
            <Trash2 size={14} />
          </button>
        </div>
      ),
      className: "w-24",
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-text-primary flex items-center gap-2">
            <Package size={18} /> Product Catalog
          </h1>
          <p className="text-xs text-text-muted mt-1">
            Global list of commercial product names available on assets (all tenants).
          </p>
        </div>
        <button
          onClick={() => setModal({ open: true })}
          className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white text-sm px-3 py-2 rounded-md transition-colors"
        >
          <Plus size={16} /> Add product
        </button>
      </div>

      <div className="bg-card border border-border rounded-lg">
        <DataTable
          columns={columns}
          data={products ?? []}
          loading={isLoading}
          emptyMessage="No products in the catalog yet"
        />
      </div>

      {modal.open && (
        <ProductModal editing={modal.editing} onClose={() => setModal({ open: false })} />
      )}
      {deleting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-card border border-border rounded-lg w-full max-w-md shadow-xl p-5 space-y-4">
            <h2 className="text-sm font-semibold text-text-primary">Delete product?</h2>
            <p className="text-sm text-text-secondary">
              "{deleting.name}" is removed from the catalog and can no longer be assigned to assets.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setDeleting(null)}
                className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                onClick={() =>
                  deleteMutation.mutate(deleting.id, { onSuccess: () => setDeleting(null) })
                }
                disabled={deleteMutation.isPending}
                className="px-4 py-2 bg-status-failed/20 text-status-failed border border-status-failed/30 text-sm rounded-md disabled:opacity-50"
              >
                {deleteMutation.isPending ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
