import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface DrawerProps {
  title: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  /** Tailwind width class; default w-[520px]. */
  widthClass?: string;
}

/** Right-side inspector panel. Used for full values that don't belong in a
 * table cell (JSON payloads, audit diffs, run stats). */
export function Drawer({ title, onClose, children, widthClass }: DrawerProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          "relative h-full max-w-[92vw] bg-card border-l border-border shadow-2xl flex flex-col",
          widthClass ?? "w-[520px]",
        )}
      >
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border">
          <h3 className="text-sm font-semibold text-text-primary truncate">{title}</h3>
          <button
            type="button"
            title="Close"
            onClick={onClose}
            className="p-1 rounded text-text-secondary hover:text-text-primary hover:bg-elevated transition-colors"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
