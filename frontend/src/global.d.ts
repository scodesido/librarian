declare global {
  const API_URL: string;

  // Build target baked in by Vite (see Dockerfile ARG APP_TARGET). Augments
  // the ImportMetaEnv from vite/client so import.meta.env.VITE_APP_TARGET is
  // typed.
  interface ImportMetaEnv {
    readonly VITE_APP_TARGET?: string;
  }
}

export {};
