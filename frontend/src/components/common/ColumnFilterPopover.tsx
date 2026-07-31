import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check } from "lucide-react";
import { parseFilterInput } from "@/lib/columnFilters";

interface ColumnFilterPopoverProps {
  /** Current committed tokens for this column. */
  values: string[];
  onChange: (values: string[]) => void;
  /** Suggestions derived from visible/available rows. */
  distinctValues: string[];
  onClose: () => void;
  /** The header filter button the popover anchors to. */
  anchorEl: HTMLElement;
}

const WIDTH = 264;

/** Excel-style column filter: free text (comma-separated tokens, OR) on top,
 * clickable distinct values below. Rendered in a portal — the table's
 * overflow-x-auto wrapper would clip an absolutely positioned child. */
export function ColumnFilterPopover({
  values,
  onChange,
  distinctValues,
  onClose,
  anchorEl,
}: ColumnFilterPopoverProps) {
  const [text, setText] = useState(values.join(", "));
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  const tokens = parseFilterInput(text);

  useLayoutEffect(() => {
    const rect = anchorEl.getBoundingClientRect();
    const left = Math.min(rect.left, window.innerWidth - WIDTH - 8);
    setPos({ top: rect.bottom + 4, left: Math.max(8, left) });
  }, [anchorEl]);

  useEffect(() => {
    inputRef.current?.focus();
    const onMouseDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!panelRef.current?.contains(t) && !anchorEl.contains(t)) onClose();
    };
    // Close on any outer scroll/resize: fixed positioning would drift.
    const onScroll = (e: Event) => {
      if (!panelRef.current?.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onMouseDown);
    window.addEventListener("scroll", onScroll, { capture: true });
    window.addEventListener("resize", onClose);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("scroll", onScroll, { capture: true });
      window.removeEventListener("resize", onClose);
      document.removeEventListener("keydown", onKey);
    };
  }, [anchorEl, onClose]);

  const commit = (next: string[]) => {
    onChange(next);
    onClose();
  };

  const toggle = (value: string) => {
    const has = tokens.some((t) => t.toLowerCase() === value.toLowerCase());
    const next = has
      ? tokens.filter((t) => t.toLowerCase() !== value.toLowerCase())
      : [...tokens, value];
    setText(next.join(", "));
  };

  if (!pos) return null;

  return createPortal(
    <div
      ref={panelRef}
      style={{ position: "fixed", top: pos.top, left: pos.left, width: WIDTH }}
      className="z-50 bg-elevated border border-border rounded-md shadow-xl text-sm normal-case font-normal tracking-normal"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="p-2 border-b border-border-subtle">
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit(parseFilterInput(text));
          }}
          placeholder="value1, value2, …"
          className="w-full bg-card border border-border rounded px-2.5 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
        />
      </div>
      {distinctValues.length > 0 && (
        <ul className="max-h-64 overflow-y-auto py-1">
          {distinctValues.map((v) => {
            const selected = tokens.some(
              (t) => t.toLowerCase() === v.toLowerCase(),
            );
            return (
              <li key={v}>
                <button
                  type="button"
                  onClick={() => toggle(v)}
                  className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-text-secondary hover:bg-card hover:text-text-primary transition-colors"
                >
                  <span className="w-4 shrink-0 text-accent">
                    {selected && <Check size={13} />}
                  </span>
                  <span className="truncate">{v}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex items-center justify-between px-2 py-1.5 border-t border-border-subtle">
        <button
          type="button"
          onClick={() => commit([])}
          className="px-2 py-1 text-xs text-text-muted hover:text-text-primary transition-colors"
        >
          Clear
        </button>
        <button
          type="button"
          onClick={() => commit(parseFilterInput(text))}
          className="px-2.5 py-1 text-xs font-medium rounded bg-accent text-white hover:bg-accent-hover transition-colors"
        >
          Apply
        </button>
      </div>
    </div>,
    document.body,
  );
}
