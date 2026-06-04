import { useState } from "react";
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
import AccountPanel from "../account/account-panel";
import SearchPanel from "./search-panel";
import SyncPanel from "./sync-panel";
import WorkerEvents from "./worker-events";
import { useAccountReadiness } from "./use-account-readiness";
import { syncFullyReady, usePipelineCounts } from "./use-pipeline-counts";

interface HomeScreenProps {
  me: Me;
  onLoggedOut: () => void;
}

// Onboarding is sequential: configure your account (models + tokens) before
// you can sync, and finish syncing before you can search. The tabs render in
// that order and later steps stay disabled until their prerequisite is met.
const TAB_ORDER = ["account", "sync", "search"] as const;
type TabValue = (typeof TAB_ORDER)[number];
const ACTIVE_TAB_STORAGE_KEY = "librarian.active_tab";

function HomeScreen({ me, onLoggedOut }: HomeScreenProps) {
  const onLogout = async () => {
    await api("/oauth/google/logout", { method: "POST" });
    onLoggedOut();
  };

  // Tabs keep their panels mounted by default, so each tab's state persists
  // when the user switches away and back: an in-progress search isn't lost
  // when they peek at sync, the pipeline SSE stream stays open, etc.
  const { counts, streamError } = usePipelineCounts();
  const account = useAccountReadiness();

  const enabled: Record<TabValue, boolean> = {
    account: true,
    sync: account.ready,
    search: account.ready && syncFullyReady(counts),
  };

  // Remember the last tab the user chose; restore it on load but never show a
  // tab that's currently gated — fall back to the furthest enabled one. We
  // store the user's intent and only *render* the clamped value, so a tab
  // re-enabling (e.g. sync finishing) snaps back to where they wanted to be.
  const [stored, setStored] = useState<TabValue>(() => {
    const saved = localStorage.getItem(ACTIVE_TAB_STORAGE_KEY);
    return TAB_ORDER.includes(saved as TabValue)
      ? (saved as TabValue)
      : "account";
  });
  const active: TabValue = enabled[stored]
    ? stored
    : ([...TAB_ORDER].reverse().find((t) => enabled[t]) ?? "account");

  const onTabChange = (value: string | null) => {
    if (value === null || !TAB_ORDER.includes(value as TabValue)) return;
    setStored(value as TabValue);
    localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, value);
  };

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
        <Tabs value={active} onChange={onTabChange}>
          <Tabs.List>
            <Tabs.Tab value="account">Account</Tabs.Tab>
            <Tabs.Tab value="sync" disabled={!enabled.sync}>
              Sync
            </Tabs.Tab>
            <Tabs.Tab value="search" disabled={!enabled.search}>
              Search
            </Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="account" pt="md">
            <AccountPanel onChanged={account.refresh} />
          </Tabs.Panel>
          <Tabs.Panel value="sync" pt="md">
            <Stack gap="xl">
              <SyncPanel counts={counts} streamError={streamError} />
              <WorkerEvents />
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="search" pt="md">
            <SearchPanel />
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </Container>
  );
}

export default HomeScreen;
