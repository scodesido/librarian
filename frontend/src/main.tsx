import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MantineProvider } from "@mantine/core";
import "@mantine/core/styles.css";
import App from "./app/app.tsx";
import AdminApp from "./admin/admin-app.tsx";

// Which app this build serves. VITE_APP_TARGET is baked in at build time
// (Dockerfile ARG → ENV), so this ternary constant-folds and the unused app
// tree-shakes out of the bundle. Defaults to the user webapp.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider>
      {import.meta.env.VITE_APP_TARGET === "adminpanel" ? (
        <AdminApp />
      ) : (
        <App />
      )}
    </MantineProvider>
  </StrictMode>,
);
