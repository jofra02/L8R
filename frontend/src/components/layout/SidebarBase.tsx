import { NavLink } from "react-router-dom";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export interface NavItem {
  label: string;
  path: string;
  icon: React.ReactNode;
  permission?: string;
  disabled?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

interface SidebarBaseProps {
  collapsed: boolean;
  onToggle: () => void;
  groups: NavGroup[];
  hasPermission: (perm: string) => boolean;
}

export function SidebarBase({ collapsed, onToggle, groups, hasPermission }: SidebarBaseProps) {
  return (
    <aside
      className={cn(
        "fixed left-0 top-16 bottom-8 bg-sidebar border-r border-border z-40 transition-all duration-200 flex flex-col",
        collapsed ? "w-16" : "w-64",
      )}
    >
      <nav className="flex-1 overflow-y-auto py-4 space-y-6">
        {groups.map((group) => {
          const visibleItems = group.items.filter(
            (item) => item.disabled || !item.permission || hasPermission(item.permission),
          );
          if (visibleItems.length === 0) return null;

          return (
            <div key={group.label}>
              {!collapsed && (
                <p className="px-4 mb-2 text-[11px] font-semibold tracking-wider text-text-muted uppercase">
                  {group.label}
                </p>
              )}
              <ul className="space-y-0.5">
                {visibleItems.map((item) => (
                  <li key={item.label}>
                    {item.disabled ? (
                      <span
                        className={cn(
                          "flex items-center gap-3 px-4 py-2 text-text-muted cursor-not-allowed opacity-40",
                          collapsed && "justify-center px-0",
                        )}
                        title={collapsed ? item.label : undefined}
                      >
                        {item.icon}
                        {!collapsed && <span className="text-sm">{item.label}</span>}
                      </span>
                    ) : (
                      <NavLink
                        to={item.path}
                        end={item.path === "/" || item.path.match(/^\/t\/[^/]+$/) !== null || item.path === "/global"}
                        className={({ isActive }) =>
                          cn(
                            "flex items-center gap-3 px-4 py-2 text-sm transition-colors relative",
                            collapsed && "justify-center px-0",
                            isActive
                              ? "text-text-primary bg-accent/10 before:absolute before:left-0 before:top-0 before:bottom-0 before:w-0.5 before:bg-accent"
                              : "text-text-secondary hover:text-text-primary hover:bg-elevated/50",
                          )
                        }
                        title={collapsed ? item.label : undefined}
                      >
                        {item.icon}
                        {!collapsed && <span>{item.label}</span>}
                      </NavLink>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </nav>

      <button
        onClick={onToggle}
        className="flex items-center justify-center h-10 border-t border-border text-text-secondary hover:text-text-primary transition-colors"
      >
        {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
      </button>
    </aside>
  );
}
