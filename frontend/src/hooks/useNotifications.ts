import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { listNotifications, resendNotification } from "@/api/endpoints";

export function useNotifications(filters: Record<string, string | number | undefined>) {
  return useQuery({
    queryKey: ["notifications", filters],
    queryFn: () => listNotifications(filters),
  });
}

export function useResendNotification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (deliveryId: string) => resendNotification(deliveryId),
    onSuccess: (delivery) => {
      if (delivery.status === "delivered") {
        toast.success("Notification delivered");
      } else {
        toast.error(`Resend failed: ${delivery.error ?? "unknown error"}`);
      }
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail?.message || e?.response?.data?.detail || "Failed to resend"),
  });
}
