"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, apiFetch } from "./api";
import type { CurrentShop, Me } from "./types";

type Status = "loading" | "authenticated" | "unauthenticated" | "error";

interface SessionContextValue {
  status: Status;
  me: Me | null;
  error: ApiError | null;
  refresh: () => Promise<Me | null>;
  setMe: (me: Me) => void;
  logout: (allDevices?: boolean) => Promise<void>;
  switchShop: (shopId: string) => Promise<CurrentShop>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

/** Session state derived from GET /auth/me. The cookie itself is httpOnly and never read here. */
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMeState] = useState<Me | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const applySuccess = useCallback((data: Me) => {
    setMeState(data);
    setStatus("authenticated");
    setError(null);
  }, []);

  const applyFailure = useCallback((err: unknown) => {
    const apiError = err instanceof ApiError ? err : new ApiError(0, "UNKNOWN", "Unexpected error");
    setMeState(null);
    setError(apiError);
    setStatus(apiError.isUnauthenticated ? "unauthenticated" : "error");
  }, []);

  const refresh = useCallback(
    () =>
      apiFetch<Me>("/auth/me").then(
        (data) => {
          applySuccess(data);
          return data;
        },
        (err) => {
          applyFailure(err);
          return null;
        },
      ),
    [applySuccess, applyFailure],
  );

  useEffect(() => {
    let active = true;
    apiFetch<Me>("/auth/me").then(
      (data) => active && applySuccess(data),
      (err) => active && applyFailure(err),
    );
    return () => {
      active = false;
    };
  }, [applySuccess, applyFailure]);

  const setMe = useCallback((next: Me) => {
    setMeState(next);
    setStatus("authenticated");
    setError(null);
  }, []);

  const logout = useCallback(async (allDevices = false) => {
    try {
      await apiFetch<void>(allDevices ? "/auth/logout-all" : "/auth/logout", { method: "POST" });
    } finally {
      setMeState(null);
      setStatus("unauthenticated");
    }
  }, []);

  const switchShop = useCallback(
    async (shopId: string) => {
      const current = await apiFetch<CurrentShop>("/session/active-shop", {
        method: "POST",
        body: { shop_id: shopId },
      });
      await refresh();
      return current;
    },
    [refresh],
  );

  const value = useMemo(
    () => ({ status, me, error, refresh, setMe, logout, switchShop }),
    [status, me, error, refresh, setMe, logout, switchShop],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}
