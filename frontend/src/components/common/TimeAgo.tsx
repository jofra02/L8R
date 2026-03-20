import { timeAgo, formatDate } from "@/lib/utils";

interface TimeAgoProps {
  date: string | null | undefined;
}

export function TimeAgo({ date }: TimeAgoProps) {
  if (!date) return <span className="text-text-muted">-</span>;

  return (
    <span className="text-text-secondary text-sm cursor-default" title={formatDate(date)}>
      {timeAgo(date)}
    </span>
  );
}
