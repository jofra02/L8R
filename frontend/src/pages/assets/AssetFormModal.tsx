import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  useAssetProducts,
  useAssetTypes,
  useCreateAsset,
  useCreateAssetProduct,
  useMcpPacks,
  useUpdateAsset,
} from "@/hooks/useAssets";
import { useAuth } from "@/hooks/useAuth";
import type { Asset, AssetCreatePayload, AssetTypeField, McpConnection } from "@/api/types";

const inputClass =
  "w-full bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent";

const ASSET_STATUS_OPTIONS = ["active", "inactive", "maintenance", "retired"];
const CRITICALITY_OPTIONS = ["", "low", "medium", "high", "critical"];

interface Props {
  onClose: () => void;
  editing?: Asset;
}

// --- Dynamic per-type attribute fields ---

function DynamicField({
  field,
  value,
  onChange,
}: {
  field: AssetTypeField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const label = field.label ?? field.key;
  if (field.type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-sm text-text-secondary">
        <input type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
    );
  }
  if (field.type === "enum") {
    return (
      <div>
        <label className="block text-xs text-text-secondary mb-1">{label}</label>
        <select value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value || undefined)} className={inputClass}>
          <option value="">—</option>
          {(field.enum ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>
    );
  }
  if (field.type === "json") {
    return (
      <div>
        <label className="block text-xs text-text-secondary mb-1">{label} (JSON)</label>
        <textarea
          value={typeof value === "string" ? value : value != null ? JSON.stringify(value, null, 2) : ""}
          onChange={(e) => onChange(e.target.value)}
          rows={3}
          className={`${inputClass} font-mono text-xs`}
        />
      </div>
    );
  }
  if (field.type === "string_list") {
    return (
      <div>
        <label className="block text-xs text-text-secondary mb-1">{label} (comma-separated)</label>
        <input
          type="text"
          value={Array.isArray(value) ? value.join(", ") : (value as string) ?? ""}
          onChange={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
          className={inputClass}
        />
      </div>
    );
  }
  const inputType =
    field.type === "integer" || field.type === "number" ? "number"
    : field.type === "date" ? "date"
    : field.type === "datetime" ? "datetime-local"
    : "text";
  return (
    <div>
      <label className="block text-xs text-text-secondary mb-1">
        {label}{field.required ? " *" : ""}{field.sensitive ? " (sensitive)" : ""}
      </label>
      <input
        type={inputType}
        value={(value as string | number) ?? ""}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") return onChange(undefined);
          if (field.type === "integer") return onChange(parseInt(raw, 10));
          if (field.type === "number") return onChange(parseFloat(raw));
          onChange(raw);
        }}
        required={field.required}
        className={inputClass}
      />
    </div>
  );
}

// --- Modal ---

export function AssetFormModal({ onClose, editing }: Props) {
  const isEdit = !!editing;
  const { data: types } = useAssetTypes();
  const createMutation = useCreateAsset();
  const updateMutation = useUpdateAsset();
  const isPending = createMutation.isPending || updateMutation.isPending;

  const [name, setName] = useState(editing?.name ?? "");
  const [ref, setRef] = useState(editing?.ref ?? "");
  const [assetType, setAssetType] = useState(editing?.asset_type ?? "");
  const [manufacturer, setManufacturer] = useState(editing?.manufacturer ?? "");
  const [model, setModel] = useState(editing?.model ?? "");
  const [productName, setProductName] = useState(editing?.product_name ?? "");
  const [serial, setSerial] = useState(editing?.serial_number ?? "");
  const [location, setLocation] = useState(editing?.location ?? "");
  const [owner, setOwner] = useState(editing?.owner ?? "");
  const [ip, setIp] = useState(editing?.ip_address ?? "");
  const [fqdn, setFqdn] = useState(editing?.fqdn ?? "");
  const [status, setStatus] = useState(editing?.status ?? "active");
  const [criticality, setCriticality] = useState(editing?.criticality ?? "");
  const [tags, setTags] = useState((editing?.tags ?? []).join(", "));
  const [attrs, setAttrs] = useState<Record<string, unknown>>(() => {
    const a = { ...(editing?.attributes ?? {}) };
    delete a["legacy_role"];
    return a;
  });

  // MCP section
  const wasManaged = editing?.managed ?? false;
  const [mcpEnabled, setMcpEnabled] = useState(wasManaged);
  const { data: packs } = useMcpPacks(mcpEnabled);
  const [packKey, setPackKey] = useState<string>(() => {
    const cfg = editing?.mcp_config;
    return cfg ? `${cfg["vendor"]}/${cfg["appliance"]}` : "";
  });
  const [host, setHost] = useState((editing?.mcp_config?.["host"] as string) ?? "");
  const [port, setPort] = useState(String(editing?.mcp_config?.["port"] ?? 443));
  const [osVersion, setOsVersion] = useState((editing?.mcp_config?.["os_version"] as string) ?? "");
  const [token, setToken] = useState("");
  const [verifySsl, setVerifySsl] = useState(Boolean(editing?.mcp_config?.["verify_ssl"]));
  const [primary, setPrimary] = useState(Boolean(editing?.mcp_config?.["primary"]));

  const typeDef = useMemo(() => types?.find((t) => t.type_id === assetType), [types, assetType]);

  // Product catalog (global, select-only; quick-add for catalog managers)
  const { hasPermission } = useAuth();
  const canManageProducts = hasPermission("asset_products:manage");
  const { data: products } = useAssetProducts();
  const createProductMutation = useCreateAssetProduct();
  const [addingProduct, setAddingProduct] = useState(false);
  const [newProduct, setNewProduct] = useState("");
  // An edited asset can hold a name no longer in the catalog (deleted after
  // assignment); keep it selectable so the value round-trips.
  const staleProduct =
    productName && !products?.some((p) => p.name === productName) ? productName : null;

  const handleQuickAddProduct = () => {
    const name = newProduct.trim();
    if (!name) return;
    createProductMutation.mutate(name, {
      onSuccess: (product) => {
        setProductName(product.name);
        setNewProduct("");
        setAddingProduct(false);
      },
    });
  };

  const buildMcpConnection = (): McpConnection | undefined => {
    if (!mcpEnabled) return undefined;
    const pack = packs?.find((p) => `${p.vendor}/${p.appliance}` === packKey) ?? packs?.[0];
    return {
      vendor: pack?.vendor ?? "fortinet",
      appliance: pack?.appliance ?? "fortigate",
      device_type: pack?.device_type ?? "fortios",
      os_version: osVersion || undefined,
      host,
      port: parseInt(port, 10) || 443,
      token: token || undefined,
      verify_ssl: verifySsl,
      primary,
    };
  };

  const buildAttributes = (): Record<string, unknown> | undefined => {
    if (!typeDef) return Object.keys(attrs).length ? attrs : undefined;
    const out: Record<string, unknown> = { ...attrs };
    for (const f of typeDef.fields) {
      if (f.type === "json" && typeof out[f.key] === "string") {
        const raw = (out[f.key] as string).trim();
        if (!raw) { delete out[f.key]; continue; }
        try {
          out[f.key] = JSON.parse(raw);
        } catch {
          throw new Error(`Invalid JSON in field "${f.label ?? f.key}"`);
        }
      }
      if (out[f.key] === undefined) delete out[f.key];
    }
    return out;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return toast.error("Name is required");
    if (!assetType) return toast.error("Asset type is required");
    if (mcpEnabled && !host.trim()) return toast.error("MCP host is required");
    if (mcpEnabled && !isEdit && !token.trim()) return toast.error("MCP API token is required");

    let attributes: Record<string, unknown> | undefined;
    try {
      attributes = buildAttributes();
    } catch (err: any) {
      return toast.error(err.message);
    }

    const common: AssetCreatePayload = {
      name: name.trim(),
      ref: ref.trim() || undefined,
      asset_type: assetType,
      manufacturer: manufacturer.trim() || null,
      model: model.trim() || null,
      product_name: productName || null,
      serial_number: serial.trim() || null,
      location: location.trim() || null,
      owner: owner.trim() || null,
      ip_address: ip.trim() || null,
      fqdn: fqdn.trim() || null,
      status,
      criticality: criticality || null,
      tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
      attributes,
    };

    if (isEdit) {
      const body: Record<string, unknown> = { ...common };
      // PATCH semantics: never send nulls for untouched empty optionals.
      for (const k of Object.keys(body)) if (body[k] === null) delete body[k];
      const mcp = buildMcpConnection();
      if (mcp) body.mcp_connection = mcp;
      else if (wasManaged && !mcpEnabled) body.mcp_managed = false;
      updateMutation.mutate({ id: editing!.id, body }, { onSuccess: onClose });
    } else {
      createMutation.mutate({ ...common, mcp_connection: buildMcpConnection() }, { onSuccess: onClose });
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-card border border-border rounded-lg w-full max-w-2xl shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">
            {isEdit ? "Edit Asset" : "Add Asset"}
          </h2>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-text-secondary mb-1">Name *</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required className={inputClass} />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1" title="Human reference slug for search and imports. Device routing always uses the asset's internal id.">Ref (reference slug)</label>
              <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="defaults to name" className={inputClass} />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Type *</label>
              <select value={assetType} onChange={(e) => setAssetType(e.target.value)} required className={inputClass}>
                <option value="">Select type...</option>
                {types?.map((t) => <option key={t.type_id} value={t.type_id}>{t.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Status</label>
              <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputClass}>
                {ASSET_STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Manufacturer</label>
              <input value={manufacturer} onChange={(e) => setManufacturer(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Model</label>
              <input value={model} onChange={(e) => setModel(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Product</label>
              {addingProduct ? (
                <div className="flex gap-2">
                  <input
                    value={newProduct}
                    onChange={(e) => setNewProduct(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") { e.preventDefault(); handleQuickAddProduct(); }
                      if (e.key === "Escape") { setAddingProduct(false); setNewProduct(""); }
                    }}
                    placeholder="New product name"
                    autoFocus
                    className={inputClass}
                  />
                  <button
                    type="button"
                    onClick={handleQuickAddProduct}
                    disabled={createProductMutation.isPending || !newProduct.trim()}
                    className="px-3 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md disabled:opacity-50"
                  >
                    Add
                  </button>
                  <button
                    type="button"
                    onClick={() => { setAddingProduct(false); setNewProduct(""); }}
                    className="px-2 py-2 text-sm text-text-secondary hover:text-text-primary"
                  >
                    ✕
                  </button>
                </div>
              ) : (
                <div className="flex gap-2">
                  <select
                    value={productName}
                    onChange={(e) => setProductName(e.target.value)}
                    className={inputClass}
                  >
                    <option value="">—</option>
                    {staleProduct && (
                      <option value={staleProduct}>{staleProduct} (not in catalog)</option>
                    )}
                    {products?.map((p) => (
                      <option key={p.id} value={p.name}>{p.name}</option>
                    ))}
                  </select>
                  {canManageProducts && (
                    <button
                      type="button"
                      onClick={() => setAddingProduct(true)}
                      title="Add product to the global catalog"
                      className="px-3 py-2 bg-elevated border border-border rounded-md text-sm text-text-secondary hover:text-text-primary"
                    >
                      +
                    </button>
                  )}
                </div>
              )}
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Serial number</label>
              <input value={serial} onChange={(e) => setSerial(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Criticality</label>
              <select value={criticality} onChange={(e) => setCriticality(e.target.value)} className={inputClass}>
                {CRITICALITY_OPTIONS.map((c) => <option key={c} value={c}>{c || "—"}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">IP address</label>
              <input value={ip} onChange={(e) => setIp(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">FQDN</label>
              <input value={fqdn} onChange={(e) => setFqdn(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Location</label>
              <input value={location} onChange={(e) => setLocation(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label className="block text-xs text-text-secondary mb-1">Owner</label>
              <input value={owner} onChange={(e) => setOwner(e.target.value)} className={inputClass} />
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-text-secondary mb-1">Tags (comma-separated)</label>
              <input value={tags} onChange={(e) => setTags(e.target.value)} className={inputClass} />
            </div>
          </div>

          {/* Type-specific attributes (schema-driven) */}
          {typeDef && typeDef.fields.length > 0 && (
            <div className="border-t border-border pt-4 space-y-3">
              <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
                {typeDef.label} attributes
              </p>
              <div className="grid grid-cols-2 gap-3">
                {typeDef.fields.map((f) => (
                  <DynamicField
                    key={f.key}
                    field={f}
                    value={attrs[f.key]}
                    onChange={(v) => setAttrs((prev) => ({ ...prev, [f.key]: v }))}
                  />
                ))}
              </div>
            </div>
          )}

          {/* MCP managed device */}
          <div className="border-t border-border pt-4 space-y-3">
            <label className="flex items-center gap-2 text-sm text-text-primary">
              <input type="checkbox" checked={mcpEnabled} onChange={(e) => setMcpEnabled(e.target.checked)} />
              MCP managed device
            </label>
            {mcpEnabled && (
              <div className="grid grid-cols-2 gap-3">
                <div className="col-span-2">
                  <label className="block text-xs text-text-secondary mb-1">Appliance</label>
                  <select value={packKey} onChange={(e) => setPackKey(e.target.value)} className={inputClass}>
                    {(packs ?? []).map((p) => (
                      <option key={p.pack_key} value={`${p.vendor}/${p.appliance}`}>
                        {p.display_name} ({p.version})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-text-secondary mb-1">Host *</label>
                  <input value={host} onChange={(e) => setHost(e.target.value)} className={inputClass} />
                </div>
                <div>
                  <label className="block text-xs text-text-secondary mb-1">Port</label>
                  <input type="number" value={port} onChange={(e) => setPort(e.target.value)} className={inputClass} />
                </div>
                <div>
                  <label className="block text-xs text-text-secondary mb-1">OS / firmware version</label>
                  <input value={osVersion} onChange={(e) => setOsVersion(e.target.value)} placeholder="e.g. 7.4.5" className={inputClass} />
                </div>
                <div>
                  <label className="block text-xs text-text-secondary mb-1">API token {isEdit ? "" : "*"}</label>
                  <input
                    type="password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder={isEdit ? "Unchanged" : ""}
                    className={inputClass}
                  />
                </div>
                <label className="flex items-center gap-2 text-sm text-text-secondary">
                  <input type="checkbox" checked={verifySsl} onChange={(e) => setVerifySsl(e.target.checked)} />
                  Verify SSL
                </label>
                <label className="flex items-center gap-2 text-sm text-text-secondary">
                  <input type="checkbox" checked={primary} onChange={(e) => setPrimary(e.target.checked)} />
                  Primary device
                </label>
              </div>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm rounded-md transition-colors disabled:opacity-50"
            >
              {isPending ? "Saving..." : isEdit ? "Update" : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
