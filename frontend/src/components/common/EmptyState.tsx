import { Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  title?: string;
  message?: string;
  className?: string;
}

export function EmptyState({
  title = "No data",
  message = "There are no items to display.",
  className,
}: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-16 text-text-muted", className)}>
      <Inbox size={40} className="mb-3 opacity-50" />
      <p className="text-sm font-medium">{title}</p>
      <p className="text-xs mt-1">{message}</p>
    </div>
  );
}
