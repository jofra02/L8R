import { EmptyState } from "@/components/common/EmptyState";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { Breadcrumb } from "@/components/common/Breadcrumb";
import { cn } from "@/lib/utils";
import { useWorkspace } from "../workspace/WorkspaceContext";
import type { ResourceAdapter, ResourceRef, ViewContext } from "./types";

interface ResourceDetailShellProps {
  adapter: ResourceAdapter<unknown>;
  refObj: ResourceRef;
  view: string;
  /** Whether this panel is the active workspace tab. */
  active: boolean;
  /** Grid-state key prefix for views inside this resource. */
  stateKeyPrefix: string;
  onDeleted?: () => void;
}

/** The one detail layout every navigable resource uses, regardless of type
 * or depth: breadcrumb → compact header (name · badges · actions) → view
 * tabs → full-width content. */
export function ResourceDetailShell({
  adapter,
  refObj,
  view,
  active,
  stateKeyPrefix,
  onDeleted,
}: ResourceDetailShellProps) {
  const { hrefFor, navigateTo } = useWorkspace();
  const { model, isLoading, error } = adapter.useResource(refObj);

  if (isLoading) return <LoadingSpinner className="py-16" />;
  if (error || !model) {
    return <EmptyState title="Not found" message="The resource does not exist in this tenant" />;
  }

  const views = adapter.views(model);
  const activeView = views.some((v) => v.id === view) ? view : (views[0]?.id ?? "overview");
  const Actions = adapter.Actions;
  const ctx: ViewContext = { active, stateKeyPrefix };

  return (
    <div className="space-y-3">
      <Breadcrumb
        segments={[
          ...model.ancestors.map((a) => ({
            label: a.label,
            path: a.afterPath !== undefined ? hrefFor(a.afterPath) : undefined,
          })),
          { label: model.name },
        ]}
      />

      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-base font-semibold text-text-primary truncate">{model.name}</h2>
            <span className="text-xs px-2 py-0.5 rounded bg-elevated border border-border text-text-secondary whitespace-nowrap">
              {model.typeLabel}
            </span>
            {model.badges}
          </div>
          {model.metaLine && <p className="text-xs text-text-muted mt-1">{model.metaLine}</p>}
        </div>
        {Actions && <Actions model={model} onDeleted={onDeleted} />}
      </div>

      <div className="border-b border-border flex gap-0 overflow-x-auto">
        {views.map((v) => (
          <button
            key={v.id}
            onClick={() => navigateTo(adapter.buildPath(refObj, v.id), { push: true })}
            className={cn(
              "px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap",
              activeView === v.id
                ? "border-accent text-text-primary"
                : "border-transparent text-text-muted hover:text-text-secondary",
            )}
          >
            {v.label}
          </button>
        ))}
      </div>

      <div>{adapter.renderView(activeView, model, ctx)}</div>
    </div>
  );
}
