import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface TabDescriptor {
  id: string;
  label: React.ReactNode;
  closable?: boolean;
  icon?: React.ReactNode;
}

interface TabStripProps {
  tabs: TabDescriptor[];
  activeId: string;
  onActivate: (id: string) => void;
  onClose?: (id: string) => void;
  className?: string;
}

/** Browser-style tab strip: closable tabs, horizontal overflow scroll,
 * middle-click close. Presentation-only — state lives in the parent. */
export function TabStrip({ tabs, activeId, onActivate, onClose, className }: TabStripProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    containerRef.current
      ?.querySelector<HTMLElement>(`[data-tab-id="${CSS.escape(activeId)}"]`)
      ?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }, [activeId]);

  return (
    <div
      ref={containerRef}
      className={cn("flex items-end gap-0 border-b border-border overflow-x-auto", className)}
    >
      {tabs.map((tab) => {
        const active = tab.id === activeId;
        return (
          <button
            key={tab.id}
            type="button"
            data-tab-id={tab.id}
            onClick={() => onActivate(tab.id)}
            onAuxClick={(e) => {
              if (e.button === 1 && tab.closable && onClose) onClose(tab.id);
            }}
            className={cn(
              "group flex items-center gap-2 px-4 py-2 text-sm whitespace-nowrap border-b-2 -mb-px max-w-[220px] shrink-0 transition-colors",
              active
                ? "border-accent text-text-primary bg-card rounded-t-md"
                : "border-transparent text-text-muted hover:text-text-secondary hover:bg-elevated/50",
            )}
          >
            {tab.icon && <span className="shrink-0">{tab.icon}</span>}
            <span className="truncate">{tab.label}</span>
            {tab.closable && onClose && (
              <span
                role="button"
                tabIndex={-1}
                title="Close tab"
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(tab.id);
                }}
                className={cn(
                  "shrink-0 p-0.5 rounded hover:bg-elevated hover:text-text-primary transition-colors",
                  active ? "opacity-100" : "opacity-0 group-hover:opacity-100",
                )}
              >
                <X size={13} />
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
