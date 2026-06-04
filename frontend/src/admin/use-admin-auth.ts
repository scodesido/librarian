import { useCallback, useState } from "react";
import {
  clearAdminPassword,
  getAdminPassword,
  storeAdminPassword,
} from "./admin-client";

export interface AdminAuth {
  status: "anonymous" | "authed";
  error: string | null;
  // Accept a password and treat the admin as signed in. Validation is
  // optimistic: the first /admin call confirms it, and `reject` flips back
  // to the login screen if the server says it's wrong.
  login: (password: string) => void;
  logout: () => void;
  reject: (message: string) => void;
}

export function useAdminAuth(): AdminAuth {
  const [password, setPassword] = useState<string | null>(() =>
    getAdminPassword(),
  );
  const [error, setError] = useState<string | null>(null);

  // Stable callbacks (setState setters are stable) so consumers can use them
  // as effect dependencies without re-running.
  const login = useCallback((pw: string) => {
    storeAdminPassword(pw);
    setError(null);
    setPassword(pw);
  }, []);

  const logout = useCallback(() => {
    clearAdminPassword();
    setError(null);
    setPassword(null);
  }, []);

  const reject = useCallback((message: string) => {
    clearAdminPassword();
    setPassword(null);
    setError(message);
  }, []);

  return {
    status: password === null ? "anonymous" : "authed",
    error,
    login,
    logout,
    reject,
  };
}
