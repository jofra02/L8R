import { useState, useEffect } from "react";
import { format } from "date-fns";
import { getHealth } from "@/api/endpoints";

export function Footer() {
  const [time, setTime] = useState(new Date());
  const [apiStatus, setApiStatus] = useState<"connected" | "disconnected">("disconnected");

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let mounted = true;
    async function check() {
      try {
        await getHealth();
        if (mounted) setApiStatus("connected");
      } catch {
        if (mounted) setApiStatus("disconnected");
      }
    }
    check();
    const interval = setInterval(check, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <footer className="fixed bottom-0 left-0 right-0 h-8 bg-sidebar border-t border-border flex items-center justify-between px-6 text-xs text-text-muted z-50">
      <span>v0.2.0</span>
      <div className="flex items-center gap-4">
        <span className="flex items-center gap-1.5">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              apiStatus === "connected" ? "bg-status-completed" : "bg-status-failed"
            }`}
          />
          {apiStatus === "connected" ? "Connected" : "Disconnected"}
        </span>
        <span className="font-mono">{format(time, "HH:mm")}</span>
      </div>
    </footer>
  );
}
