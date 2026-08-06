import { Fragment } from "react";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

export interface BreadcrumbSegment {
  label: string;
  /** Navigable segments carry a path; the current segment omits it. */
  path?: string;
}

/** Hierarchy breadcrumb (Assets / FortiEDR / Discovered inventory / DC1). Every
 * segment with a path is navigable; the last one is the current resource. */
export function Breadcrumb({ segments, className }: { segments: BreadcrumbSegment[]; className?: string }) {
  return (
    <nav aria-label="Breadcrumb" className={cn("flex items-center flex-wrap gap-1 text-sm min-w-0", className)}>
      {segments.map((seg, i) => (
        <Fragment key={`${seg.label}-${i}`}>
          {i > 0 && <ChevronRight size={13} className="text-text-muted shrink-0" />}
          {seg.path ? (
            <Link
              to={seg.path}
              className="text-text-secondary hover:text-accent transition-colors truncate max-w-[220px]"
              title={seg.label}
            >
              {seg.label}
            </Link>
          ) : (
            <span className="text-text-primary font-medium truncate max-w-[260px]" title={seg.label}>
              {seg.label}
            </span>
          )}
        </Fragment>
      ))}
    </nav>
  );
}
