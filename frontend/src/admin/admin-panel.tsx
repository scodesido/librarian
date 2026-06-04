import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Container,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import TreeExplorer from "../components/tree-explorer";
import { adminApi } from "./admin-client";

interface AdminUser {
  user_id: number;
  user_name: string;
  created_at: string;
}

function AdminPanel({
  onReject,
  onLogout,
}: {
  onReject: (message: string) => void;
  onLogout: () => void;
}) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const resp = await adminApi("/admin/users");
        if (cancelled) return;
        if (resp.status === 401 || resp.status === 403) {
          onReject("Invalid admin password");
          return;
        }
        if (resp.status === 503) {
          setLoadError("Admin panel is not configured on the server.");
          return;
        }
        if (!resp.ok) {
          setLoadError(`Failed to load users (${resp.status})`);
          return;
        }
        const body = (await resp.json()) as { users: AdminUser[] };
        if (cancelled) return;
        setUsers(body.users);
        setSelected(body.users.length > 0 ? body.users[0].user_id : null);
      } catch {
        // A rejected fetch (backend down, network drop, CORS preflight
        // blocked) never reaches the status checks above, so without this
        // the panel would hang on the loader with a possibly-stale password
        // still cached. Surface it instead — the always-visible Log out
        // button then lets the operator clear the password and retry.
        if (cancelled) return;
        setLoadError(
          "Couldn't reach the API. Check the backend is running and " +
            "reachable, then log out and back in.",
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onReject]);

  // Scoped to the selected user. Stable per user so TreeExplorer's effect
  // doesn't loop; switching user remounts the explorer (key) to reset to root.
  const loadNode = useCallback(
    (nodeId: number | null) =>
      adminApi(
        nodeId === null
          ? `/admin/tree/node?user_id=${selected}`
          : `/admin/tree/node/${nodeId}?user_id=${selected}`,
      ),
    [selected],
  );

  return (
    <Container py="lg">
      <Stack gap="lg">
        <Group justify="space-between">
          <Title order={2}>Librarian admin</Title>
          <Button variant="subtle" onClick={onLogout}>
            Log out
          </Button>
        </Group>

        {loadError !== null && (
          <Alert color="red" title="Couldn't load admin panel">
            {loadError}
          </Alert>
        )}

        {loadError === null && users === null && <Loader />}

        {users !== null && users.length === 0 && (
          <Text c="dimmed">No users yet.</Text>
        )}

        {users !== null && users.length > 0 && (
          <>
            <Select
              label="User"
              value={selected === null ? null : String(selected)}
              onChange={(v) => v !== null && setSelected(Number(v))}
              data={users.map((u) => ({
                value: String(u.user_id),
                label: `#${u.user_id} — ${u.user_name}`,
              }))}
              allowDeselect={false}
              style={{ maxWidth: 420 }}
            />
            {selected !== null && (
              <TreeExplorer key={selected} loadNode={loadNode} />
            )}
          </>
        )}
      </Stack>
    </Container>
  );
}

export default AdminPanel;
