import { useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface JsonViewerProps {
  data: unknown;
  defaultExpanded?: boolean;
  className?: string;
}

export function JsonViewer({ data, defaultExpanded = false, className }: JsonViewerProps) {
  if (data === null || data === undefined) {
    return <span className="text-text-muted text-sm">null</span>;
  }

  return (
    <div className={cn("font-mono text-xs", className)}>
      <JsonNode data={data} expanded={defaultExpanded} depth={0} />
    </div>
  );
}

function JsonNode({ data, expanded: initialExpanded, depth }: { data: unknown; expanded: boolean; depth: number }) {
  const [expanded, setExpanded] = useState(initialExpanded || depth < 1);

  if (data === null) return <span className="text-text-muted">null</span>;
  if (typeof data === "boolean") return <span className="text-severity-medium">{String(data)}</span>;
  if (typeof data === "number") return <span className="text-accent">{data}</span>;
  if (typeof data === "string") {
    if (data.length > 200) {
      return <span className="text-severity-low">"{data.slice(0, 200)}..."</span>;
    }
    return <span className="text-severity-low">"{data}"</span>;
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
                <JsonNode data={item} expanded={false} depth={depth + 1} />
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
                <span className="text-text-secondary">"{key}"</span>
                <span className="text-text-muted">: </span>
                <JsonNode data={val} expanded={false} depth={depth + 1} />
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
