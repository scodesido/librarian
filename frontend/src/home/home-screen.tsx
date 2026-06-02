import {
  Button,
  Container,
  Group,
  Stack,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import { api } from "../api/client";
import type { Me } from "../auth/use-auth";
import SettingsPanel from "../settings/settings-panel";
import SearchPanel from "./search-panel";
import SyncPanel from "./sync-panel";
import TreeExplorer from "./tree-explorer";
import WorkerEvents from "./worker-events";

interface HomeScreenProps {
  me: Me;
  onLoggedOut: () => void;
}

function HomeScreen({ me, onLoggedOut }: HomeScreenProps) {
  const onLogout = async () => {
    await api("/oauth/google/logout", { method: "POST" });
    onLoggedOut();
  };

  // Tabs keep their panels mounted by default, so each tab's state persists
  // when the user switches away and back: an in-progress search isn't lost
  // when the user peeks at the tree, the pipeline SSE stream stays open
  // across tab switches, etc.
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
        <Tabs defaultValue="sync">
          <Tabs.List>
            <Tabs.Tab value="sync">Sync</Tabs.Tab>
            <Tabs.Tab value="tree">Tree</Tabs.Tab>
            <Tabs.Tab value="search">Search</Tabs.Tab>
            <Tabs.Tab value="settings">Settings</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="sync" pt="md">
            <Stack gap="xl">
              <SyncPanel />
              <WorkerEvents />
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="tree" pt="md">
            <TreeExplorer />
          </Tabs.Panel>
          <Tabs.Panel value="search" pt="md">
            <SearchPanel />
          </Tabs.Panel>
          <Tabs.Panel value="settings" pt="md">
            <SettingsPanel />
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </Container>
  );
}

export default HomeScreen;
