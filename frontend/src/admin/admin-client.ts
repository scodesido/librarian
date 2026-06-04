// Admin requests carry the operator admin password in an X-Admin-Password
// header (see api/core/auth/admin.py). The password lives in sessionStorage
// so a page reload keeps the admin signed in for the tab's lifetime but it
// doesn't persist to disk. No cookie/credentials — admin auth is purely the
// header, kept separate from the user session.
const ADMIN_PASSWORD_KEY = "librarian.admin_password";

export function getAdminPassword(): string | null {
  return sessionStorage.getItem(ADMIN_PASSWORD_KEY);
}

export function storeAdminPassword(password: string): void {
  sessionStorage.setItem(ADMIN_PASSWORD_KEY, password);
}

export function clearAdminPassword(): void {
  sessionStorage.removeItem(ADMIN_PASSWORD_KEY);
}

export async function adminApi(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      "X-Admin-Password": getAdminPassword() ?? "",
    },
  });
}
