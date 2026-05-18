import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Group,
  Progress,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { api } from "../api/client";

interface PipelineCounts {
  files_total: number;
  files_ready: number;
  blobs_total: number;
  blobs_in_tree: number;
  nodes_total: number;
  nodes_weighted: number;
  nodes_abstracted: number;
}

const PREFIX_STORAGE_KEY = "librarian.sync_prefix";
const PREFIX_DEFAULT = "/librarian/";

function StageRow({
  label,
  current,
  total,
}: {
  label: string;
  current: number;
  total: number;
}) {
  const percent = total > 0 ? Math.round((current / total) * 100) : 0;
  return (
    <Stack gap={4}>
      <Group justify="space-between">
        <Text size="sm">{label}</Text>
        <Text size="sm" c="dimmed">
          {current} / {total} ({percent}%)
        </Text>
      </Group>
      <Progress value={percent} />
    </Stack>
  );
}

function SyncPanel() {
  const [counts, setCounts] = useState<PipelineCounts | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [prefix, setPrefix] = useState<string>(
    () => localStorage.getItem(PREFIX_STORAGE_KEY) ?? PREFIX_DEFAULT,
  );
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  useEffect(() => {
    const url = `${API_URL}/data/files/pipeline-counts/stream`;
    const source = new EventSource(url, { withCredentials: true });
    source.onmessage = (e) => {
      setStreamError(null);
      setCounts(JSON.parse(e.data) as PipelineCounts);
    };
    source.onerror = () => {
      setStreamError("Lost connection to count stream");
    };
    return () => source.close();
  }, []);

  const onPrefixChange = (value: string) => {
    setPrefix(value);
    localStorage.setItem(PREFIX_STORAGE_KEY, value);
  };

  const onSync = async () => {
    setSyncing(true);
    setSyncError(null);
    try {
      const resp = await api("/data/files/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prefix }),
      });
      if (!resp.ok) {
        const detail = await resp
          .json()
          .then((b: { detail?: string }) => b.detail)
          .catch(() => undefined);
        setSyncError(detail ?? `Sync failed (${resp.status})`);
      }
    } finally {
      setSyncing(false);
    }
  };

  const fullyReady =
    counts !== null &&
    counts.files_total > 0 &&
    counts.files_ready === counts.files_total &&
    counts.blobs_total > 0 &&
    counts.blobs_in_tree === counts.blobs_total &&
    counts.nodes_total > 0 &&
    counts.nodes_weighted === counts.nodes_total &&
    counts.nodes_abstracted === counts.nodes_total;

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="flex-end">
        <TextInput
          label="Drive folder prefix"
          value={prefix}
          onChange={(e) => onPrefixChange(e.currentTarget.value)}
          style={{ flexGrow: 1 }}
        />
        <Button onClick={onSync} loading={syncing}>
          Sync from Drive
        </Button>
      </Group>
      {counts === null ? (
        <Text c="dimmed">Connecting…</Text>
      ) : (
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={500}>Pipeline progress</Text>
            <Badge color={fullyReady ? "green" : "yellow"} variant="light">
              {fullyReady ? "Ready for retrieval" : "Building"}
            </Badge>
          </Group>
          <StageRow
            label="Files synced (ready)"
            current={counts.files_ready}
            total={counts.files_total}
          />
          <StageRow
            label="Blobs in tree"
            current={counts.blobs_in_tree}
            total={counts.blobs_total}
          />
          <StageRow
            label="Nodes weighted"
            current={counts.nodes_weighted}
            total={counts.nodes_total}
          />
          <StageRow
            label="Nodes abstracted"
            current={counts.nodes_abstracted}
            total={counts.nodes_total}
          />
        </Stack>
      )}
      {streamError !== null && <Text c="red">{streamError}</Text>}
      {syncError !== null && <Text c="red">{syncError}</Text>}
    </Stack>
  );
}

export default SyncPanel;
