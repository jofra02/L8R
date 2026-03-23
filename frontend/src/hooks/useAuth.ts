import { useState, useCallback, useEffect } from "react";
import type { TokenResponse } from "@/api/types";
import { login as apiLogin, getMe } from "@/api/endpoints";

interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  is_platform_admin: boolean;
  customer_id: string;
  available_tenants: string[];
  permissions: string[];
  must_change_password: boolean;
}

interface AuthState {
  isAuthenticated: boolean;
  user: AuthUser | null;
  loading: boolean;
}

function loadStoredUser(): AuthUser | null {
  const stored = localStorage.getItem("auth_user");
  if (!stored) return null;
  try {
    return JSON.parse(stored) as AuthUser;
  } catch {
    return null;
  }
}

export function useAuth() {
  const [state, setState] = useState<AuthState>(() => {
    const user = loadStoredUser();
    return {
      isAuthenticated: !!user && !!localStorage.getItem("access_token"),
      user,
      loading: false,
    };
  });

  const login = useCallback(async (email: string, password: string, customer_id?: string) => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const result: TokenResponse = await apiLogin({ email, password, customer_id });

      localStorage.setItem("access_token", result.access_token);
      if (result.refresh_token) {
        localStorage.setItem("refresh_token", result.refresh_token);
      }

      const user: AuthUser = {
        id: result.user?.id ?? "",
        email: result.user?.email ?? email,
        display_name: result.user?.display_name ?? "",
        is_platform_admin: result.user?.is_platform_admin ?? false,
        customer_id: result.user?.customer_id ?? "",
        available_tenants: result.user?.available_tenants ?? [],
        permissions: [],
        must_change_password: result.must_change_password,
      };

      // Fetch full context for permissions
      try {
        const ctx = await getMe();
        user.permissions = Array.isArray(ctx.permissions) ? ctx.permissions : [];
        user.customer_id = ctx.customer_id;
        user.is_platform_admin = ctx.is_platform_admin;
      } catch {
        // Proceed with basic info
      }

      localStorage.setItem("auth_user", JSON.stringify(user));
      setState({ isAuthenticated: true, user, loading: false });
      return { success: true as const, must_change_password: result.must_change_password };
    } catch (err: unknown) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("refresh_token");
      localStorage.removeItem("auth_user");
      setState({ isAuthenticated: false, user: null, loading: false });
      const message = (err as { response?: { data?: { message?: string } } })?.response?.data?.message ?? "Invalid credentials";
      return { success: false as const, error: message };
    }
  }, []);

  const logout = useCallback(() => {
    const refreshToken = localStorage.getItem("refresh_token");
    if (refreshToken) {
      // Fire and forget
      import("@/api/endpoints").then((m) => m.logout(refreshToken).catch(() => {}));
    }
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    localStorage.removeItem("auth_user");
    setState({ isAuthenticated: false, user: null, loading: false });
  }, []);

  const hasPermission = useCallback(
    (perm: string): boolean => {
      if (!state.user) return false;
      if (state.user.is_platform_admin) return true;
      return state.user.permissions.includes(perm);
    },
    [state.user],
  );

  // Backward compat
  const hasRole = useCallback(
    (_minRole: string): boolean => {
      return state.isAuthenticated;
    },
    [state.isAuthenticated],
  );

  // Re-validate on mount
  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token && !state.user) {
      getMe()
        .then((ctx) => {
          const user: AuthUser = {
            id: ctx.user_id ?? "",
            email: "",
            display_name: "",
            is_platform_admin: ctx.is_platform_admin,
            customer_id: ctx.customer_id,
            available_tenants: ctx.available_tenants ?? [],
            permissions: Array.isArray(ctx.permissions) ? ctx.permissions : [],
            must_change_password: false,
          };
          localStorage.setItem("auth_user", JSON.stringify(user));
          setState({ isAuthenticated: true, user, loading: false });
        })
        .catch(() => {
          localStorage.removeItem("access_token");
          localStorage.removeItem("refresh_token");
          localStorage.removeItem("auth_user");
          setState({ isAuthenticated: false, user: null, loading: false });
        });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return { ...state, login, logout, hasRole, hasPermission };
}
