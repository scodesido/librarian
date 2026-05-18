import { useEffect, useState } from "react";
import { Button, Group, Progress, Stack, Text, TextInput } from "@mantine/core";
import { api } from "../api/client";

// TODO: update to the new /data/files/pipeline-counts/stream endpoint. The
// backend now returns a richer PipelineCounts payload
// ({files_total, files_ready, blobs_total, blobs_in_tree, nodes_total,
//   nodes_weighted, nodes_abstracted}). The bits below still reference the
// retired StateCounts shape and the retired /state-counts/stream URL; the
// stream connection will currently 404.
interface StateCounts {
  pending: number;
  ready: number;
  total: number;
}

const PREFIX_STORAGE_KEY = "librarian.sync_prefix";
const PREFIX_DEFAULT = "/librarian/";

function SyncPanel() {
  const [counts, setCounts] = useState<StateCounts | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [prefix, setPrefix] = useState<string>(
    () => localStorage.getItem(PREFIX_STORAGE_KEY) ?? PREFIX_DEFAULT,
  );
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  useEffect(() => {
    const url = `${API_URL}/data/files/state-counts/stream`;
    const source = new EventSource(url, { withCredentials: true });
    source.onmessage = (e) => {
      setStreamError(null);
      setCounts(JSON.parse(e.data) as StateCounts);
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

  const percentReady =
    counts !== null && counts.total > 0
      ? Math.round((counts.ready / counts.total) * 100)
      : 0;

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
        <>
          <Text>
            {counts.total} total · {counts.ready} ready ({percentReady}%)
          </Text>
          <Progress value={percentReady} />
        </>
      )}
      {streamError !== null && <Text c="red">{streamError}</Text>}
      {syncError !== null && <Text c="red">{syncError}</Text>}
    </Stack>
  );
}

export default SyncPanel;
