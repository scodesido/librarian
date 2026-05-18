import {
  Button,
  Container,
  Divider,
  Group,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { api } from "../api/client";
import type { Me } from "../auth/use-auth";
import SyncPanel from "./sync-panel";
import TreeExplorer from "./tree-explorer";

interface HomeScreenProps {
  me: Me;
  onLoggedOut: () => void;
}

function HomeScreen({ me, onLoggedOut }: HomeScreenProps) {
  const onLogout = async () => {
    await api("/oauth/google/logout", { method: "POST" });
    onLoggedOut();
  };

  // SyncPanel and TreeExplorer are deliberately independent: each owns its
  // own data, error, and connection state. Promoting either into its own
  // tab later means lifting one component out and wrapping the parent in
  // <Tabs>, no internal refactor needed.
  return (
    <Container py="lg">
      <Stack gap="lg">
        <Group justify="space-between">
          <Title order={2}>Librarian</Title>
          <Group gap="md">
            <Text c="dimmed">
              {me.google !== null
                ? `Logged in as ${me.google.email}`
                : `User #${me.user_id}`}
            </Text>
            <Button variant="subtle" onClick={onLogout}>
              Log out
            </Button>
          </Group>
        </Group>
        <SyncPanel />
        <Divider />
        <TreeExplorer />
      </Stack>
    </Container>
  );
}

export default HomeScreen;
