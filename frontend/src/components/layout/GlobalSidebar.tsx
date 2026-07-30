import { LayoutDashboard, Building2, Ticket, Users, ShieldCheck, Boxes } from "lucide-react";
import { SidebarBase, type NavGroup } from "./SidebarBase";

const GLOBAL_NAV_GROUPS: NavGroup[] = [
  {
    label: "PLATFORM",
    items: [
      { label: "Dashboard", path: "/global", icon: <LayoutDashboard size={20} />, permission: "tenants:read" },
      { label: "Tenants", path: "/global/tenants", icon: <Building2 size={20} />, permission: "tenants:read" },
      { label: "Tickets", path: "/global/tickets", icon: <Ticket size={20} />, permission: "tickets:read" },
      { label: "Assets", path: "/global/assets", icon: <Boxes size={20} />, permission: "assets:read_global" },
    ],
  },
  {
    label: "ADMIN",
    items: [
      { label: "Users", path: "/global/users", icon: <Users size={20} />, permission: "users:read" },
      { label: "Profiles", path: "/global/profiles", icon: <ShieldCheck size={20} />, permission: "profiles:read" },
    ],
  },
];

interface GlobalSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  hasPermission: (perm: string) => boolean;
}

export function GlobalSidebar({ collapsed, onToggle, hasPermission }: GlobalSidebarProps) {
  return <SidebarBase collapsed={collapsed} onToggle={onToggle} groups={GLOBAL_NAV_GROUPS} hasPermission={hasPermission} />;
}
