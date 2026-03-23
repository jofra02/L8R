import {
  LayoutDashboard,
  Ticket,
  Play,
  ScrollText,
  Wrench,
  KeyRound,
  Users,
  ShieldCheck,
  Boxes,
} from "lucide-react";
import { SidebarBase, type NavGroup } from "./SidebarBase";
import { useMemo } from "react";

interface TenantSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  hasPermission: (perm: string) => boolean;
  tenantId: string;
}

export function TenantSidebar({ collapsed, onToggle, hasPermission, tenantId }: TenantSidebarProps) {
  const groups: NavGroup[] = useMemo(() => {
    const p = `/t/${tenantId}`;
    return [
      {
        label: "OPERATIONS",
        items: [
          { label: "Dashboard", path: p, icon: <LayoutDashboard size={20} />, permission: "tickets:read" },
          { label: "Tickets", path: `${p}/tickets`, icon: <Ticket size={20} />, permission: "tickets:read" },
          { label: "Runs", path: `${p}/runs`, icon: <Play size={20} />, permission: "runs:read" },
        ],
      },
      {
        label: "CONFIGURATION",
        items: [
          { label: "Inventory", path: `${p}/inventory`, icon: <Boxes size={20} />, permission: "inventory:read" },
        ],
      },
      {
        label: "OBSERVABILITY",
        items: [
          { label: "Audit Logs", path: `${p}/audit/logs`, icon: <ScrollText size={20} />, permission: "audit:read" },
          { label: "Tool Calls", path: `${p}/audit/tool-calls`, icon: <Wrench size={20} />, permission: "audit:read" },
        ],
      },
      {
        label: "ADMIN",
        items: [
          { label: "API Keys", path: `${p}/settings/keys`, icon: <KeyRound size={20} />, permission: "keys:read" },
          { label: "Users", path: `${p}/settings/users`, icon: <Users size={20} />, permission: "users:read" },
          { label: "Profiles", path: `${p}/settings/profiles`, icon: <ShieldCheck size={20} />, permission: "profiles:read" },
        ],
      },
    ];
  }, [tenantId]);

  return <SidebarBase collapsed={collapsed} onToggle={onToggle} groups={groups} hasPermission={hasPermission} />;
}
