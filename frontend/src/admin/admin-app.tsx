import AdminLogin from "./admin-login";
import AdminPanel from "./admin-panel";
import { useAdminAuth } from "./use-admin-auth";

function AdminApp() {
  const auth = useAdminAuth();

  if (auth.status === "anonymous") {
    return <AdminLogin error={auth.error} onSubmit={auth.login} />;
  }
  return <AdminPanel onReject={auth.reject} onLogout={auth.logout} />;
}

export default AdminApp;
