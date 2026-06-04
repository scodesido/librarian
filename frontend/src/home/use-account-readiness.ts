import { useEffect, useState } from "react";
import { api } from "../api/client";
import { modelRequiresToken } from "../account/slots";

interface MeResponse {
  models: Record<string, string>;
}

interface SlotStatus {
  slot: string;
  has_token: boolean;
}

interface TokensResponse {
  slots: SlotStatus[];
}

export interface AccountReadiness {
  // True once every slot whose selected model needs a token has one saved.
  // An all-Ollama setup is ready with zero tokens. Starts false so the Sync
  // and Search tabs stay gated until we've confirmed otherwise.
  ready: boolean;
  // Re-fetch after the user saves or removes a model/token in the Account tab.
  refresh: () => void;
}

// Lightweight readiness probe for tab gating. Fetches the same /settings/me
// and /settings/tokens the Account panel reads; the panel calls refresh() on
// every save/delete so this stays in sync without sharing component state.
// refresh() bumps `tick`, which re-runs the fetching effect.
export function useAccountReadiness(): AccountReadiness {
  const [ready, setReady] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const [m, t] = await Promise.all([
        api("/settings/me"),
        api("/settings/tokens"),
      ]);
      if (cancelled || !m.ok || !t.ok) return;
      const { models } = (await m.json()) as MeResponse;
      const { slots } = (await t.json()) as TokensResponse;
      if (cancelled) return;
      const hasToken = new Map(slots.map((s) => [s.slot, s.has_token]));
      const ok = Object.entries(models).every(
        ([slot, model]) =>
          !modelRequiresToken(model) || hasToken.get(slot) === true,
      );
      setReady(ok);
    };
    void load().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [tick]);

  return { ready, refresh: () => setTick((n) => n + 1) };
}
