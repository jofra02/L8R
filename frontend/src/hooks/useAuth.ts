import { useState, useCallback, useEffect } from "react";
import type { AuthContext } from "@/api/types";
import { getMe } from "@/api/endpoints";

interface AuthState {
  isAuthenticated: boolean;
  context: AuthContext | null;
  loading: boolean;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>(() => {
    const stored = localStorage.getItem("auth_context");
    return {
      isAuthenticated: !!stored,
      context: stored ? (JSON.parse(stored) as AuthContext) : null,
      loading: false,
    };
  });

  const login = useCallback(async (apiKey: string) => {
    setState((s) => ({ ...s, loading: true }));
    try {
      localStorage.setItem("api_key", apiKey);
      const ctx = await getMe();
      localStorage.setItem("auth_context", JSON.stringify(ctx));
      setState({ isAuthenticated: true, context: ctx, loading: false });
      return { success: true as const };
    } catch (err) {
      localStorage.removeItem("api_key");
      localStorage.removeItem("auth_context");
      setState({ isAuthenticated: false, context: null, loading: false });
      return { success: false as const, error: err };
    }
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("api_key");
    localStorage.removeItem("auth_context");
    setState({ isAuthenticated: false, context: null, loading: false });
  }, []);

  const hasRole = useCallback(
    (minRole: string): boolean => {
      if (!state.context) return false;
      const hierarchy = ["viewer", "operator", "tenant_admin", "platform_admin"];
      const userRank = hierarchy.indexOf(state.context.role);
      const requiredRank = hierarchy.indexOf(minRole);
      return userRank >= requiredRank;
    },
    [state.context],
  );

  // Re-validate on mount if key exists
  useEffect(() => {
    const key = localStorage.getItem("api_key");
    if (key && !state.context) {
      login(key);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return { ...state, login, logout, hasRole };
}
