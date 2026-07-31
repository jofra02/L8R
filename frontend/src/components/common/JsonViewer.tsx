import { useEffect, useState } from "react";
import { ChevronRight, ChevronDown, Copy, UnfoldVertical, FoldVertical } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface JsonViewerProps {
  data: unknown;
  defaultExpanded?: boolean;
  className?: string;
  /** Show the copy / expand-all / collapse-all / search toolbar. */
  controls?: boolean;
}

interface ForceState {
  expand: boolean;
  tick: number;
}

export function JsonViewer({ data, defaultExpanded = false, className, controls = false }: JsonViewerProps) {
  const [force, setForce] = useState<ForceState | null>(null);
  const [query, setQuery] = useState("");

  if (data === null || data === undefined) {
    return <span className="text-text-muted text-sm">null</span>;
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      toast.success("Copied to clipboard");
    } catch {
      toast.error("Copy failed");
    }
  };

  return (
    <div className={cn("font-mono text-xs", className)}>
      {controls && (
        <div className="flex items-center gap-1.5 mb-2 sticky top-0">
          <input
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              if (e.target.value) setForce((f) => ({ expand: true, tick: (f?.tick ?? 0) + 1 }));
            }}
            placeholder="Search…"
            className="flex-1 min-w-0 bg-elevated border border-border rounded px-2.5 py-1 text-xs font-sans text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
          />
          <button
            type="button"
            title="Expand all"
            onClick={() => setForce((f) => ({ expand: true, tick: (f?.tick ?? 0) + 1 }))}
            className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-elevated transition-colors"
          >
            <UnfoldVertical size={13} />
          </button>
          <button
            type="button"
            title="Collapse all"
            onClick={() => setForce((f) => ({ expand: false, tick: (f?.tick ?? 0) + 1 }))}
            className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-elevated transition-colors"
          >
            <FoldVertical size={13} />
          </button>
          <button
            type="button"
            title="Copy JSON"
            onClick={copy}
            className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-elevated transition-colors"
          >
            <Copy size={13} />
          </button>
        </div>
      )}
      <JsonNode data={data} expanded={defaultExpanded} depth={0} force={force} query={query} />
    </div>
  );
}

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-severity-medium/40 text-inherit rounded-sm">
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </>
  );
}

function JsonNode({
  data,
  expanded: initialExpanded,
  depth,
  force,
  query,
}: {
  data: unknown;
  expanded: boolean;
  depth: number;
  force: ForceState | null;
  query: string;
}) {
  const [expanded, setExpanded] = useState(initialExpanded || depth < 1);

  useEffect(() => {
    if (force) setExpanded(force.expand || depth < 1);
  }, [force, depth]);

  if (data === null) return <span className="text-text-muted">null</span>;
  if (typeof data === "boolean") return <span className="text-severity-medium">{String(data)}</span>;
  if (typeof data === "number") {
    return (
      <span className="text-accent">
        <Highlight text={String(data)} query={query} />
      </span>
    );
  }
  if (typeof data === "string") {
    const shown = data.length > 200 && !query ? `${data.slice(0, 200)}...` : data;
    return (
      <span className="text-severity-low">
        "<Highlight text={shown} query={query} />"
      </span>
    );
  }

  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="text-text-muted">[]</span>;
    return (
      <span>
        <button onClick={() => setExpanded(!expanded)} className="inline-flex items-center text-text-muted hover:text-text-secondary">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span className="ml-0.5">[{data.length}]</span>
        </button>
        {expanded && (
          <div className="ml-4 border-l border-border-subtle pl-2">
            {data.map((item, i) => (
              <div key={i} className="py-0.5">
                <JsonNode data={item} expanded={false} depth={depth + 1} force={force} query={query} />
                {i < data.length - 1 && <span className="text-text-muted">,</span>}
              </div>
            ))}
          </div>
        )}
      </span>
    );
  }

  if (typeof data === "object") {
    const entries = Object.entries(data as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-text-muted">{"{}"}</span>;
    return (
      <span>
        <button onClick={() => setExpanded(!expanded)} className="inline-flex items-center text-text-muted hover:text-text-secondary">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span className="ml-0.5">{"{"}...{"}"}</span>
        </button>
        {expanded && (
          <div className="ml-4 border-l border-border-subtle pl-2">
            {entries.map(([key, val], i) => (
              <div key={key} className="py-0.5">
                <span className="text-text-secondary">
                  "<Highlight text={key} query={query} />"
                </span>
                <span className="text-text-muted">: </span>
                <JsonNode data={val} expanded={false} depth={depth + 1} force={force} query={query} />
                {i < entries.length - 1 && <span className="text-text-muted">,</span>}
              </div>
            ))}
          </div>
        )}
      </span>
    );
  }

  return <span className="text-text-muted">{String(data)}</span>;
}
