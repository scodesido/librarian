import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

export interface Me {
  user_id: number;
  google: { sub: string; email: string } | null;
}

export type AuthState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "authenticated"; me: Me };

export function useAuth(): { state: AuthState; refresh: () => void } {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const resp = await api("/auth/me");
      if (cancelled) return;
      if (resp.status === 401) {
        setState({ status: "anonymous" });
        return;
      }
      if (!resp.ok) {
        throw new Error(`Unexpected /auth/me status: ${resp.status}`);
      }
      const me = (await resp.json()) as Me;
      if (cancelled) return;
      setState({ status: "authenticated", me });
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [tick]);

  const refresh = useCallback(() => {
    setState({ status: "loading" });
    setTick((t) => t + 1);
  }, []);

  return { state, refresh };
}
