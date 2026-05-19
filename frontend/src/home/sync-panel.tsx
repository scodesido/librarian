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
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<
    "sync" | "rebuild" | "clear" | null
  >(null);

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

  // One generic POST-action helper backs all three buttons. The only
  // per-action variation is path + (for sync) body, plus the "what is the
  // request even called" label used in error messages.
  const runAction = async (
    action: "sync" | "rebuild" | "clear",
    path: string,
    init: RequestInit,
  ) => {
    setPendingAction(action);
    setSyncing(true);
    setActionError(null);
    try {
      const resp = await api(path, init);
      if (!resp.ok) {
        const detail = await resp
          .json()
          .then((b: { detail?: string }) => b.detail)
          .catch(() => undefined);
        setActionError(detail ?? `${action} failed (${resp.status})`);
      }
    } finally {
      setSyncing(false);
      setPendingAction(null);
    }
  };

  const onSync = () =>
    runAction("sync", "/data/files/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prefix }),
    });

  const onRebuildTree = () => {
    // Confirm: this discards every blob_edge, collapses the whole tree, and
    // the workers re-attach + re-abstract from scratch. Blobs and files are
    // untouched, so no LLM re-extraction at the blob level.
    if (
      !window.confirm(
        "Rebuild the tree from scratch? Files and blobs are kept, but the " +
          "current tree structure and node abstracts are discarded; the " +
          "workers will reconstruct them. This may take a while.",
      )
    )
      return;
    runAction("rebuild", "/data/files/rebuild-tree", { method: "POST" });
  };

  const onClear = () => {
    // Confirm loudly: this is the truly destructive option — every
    // file's blobs and abstracts are deleted, so the LLM work for the
    // blob layer also gets redone next time the user syncs.
    if (
      !window.confirm(
        "Clear library: delete ALL synced files, blobs, abstracts, and " +
          "the entire tree for your account? Press Sync from Drive after " +
          "this to repopulate. This discards every LLM-generated abstract " +
          "and cannot be undone.",
      )
    )
      return;
    runAction("clear", "/data/files/clear", { method: "POST" });
  };

  const fullyReady =
    counts !== null &&
    counts.files_total > 0 &&
    counts.files_ready === counts.files_total &&
    counts.blobs_total > 0 &&
    counts.blobs_in_tree === counts.blobs_total &&
    counts.nodes_total > 0 &&
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
        <Button onClick={onSync} loading={syncing && pendingAction === "sync"}>
          Sync from Drive
        </Button>
      </Group>
      <Group gap="xs">
        <Button
          variant="default"
          size="xs"
          onClick={onRebuildTree}
          loading={syncing && pendingAction === "rebuild"}
          disabled={syncing && pendingAction !== "rebuild"}
        >
          Rebuild tree
        </Button>
        <Button
          variant="default"
          size="xs"
          color="red"
          onClick={onClear}
          loading={syncing && pendingAction === "clear"}
          disabled={syncing && pendingAction !== "clear"}
        >
          Clear library
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
            label="Files"
            current={counts.files_ready}
            total={counts.files_total}
          />
          <StageRow
            label="Blobs"
            current={counts.blobs_in_tree}
            total={counts.blobs_total}
          />
          <StageRow
            label="Nodes"
            current={counts.nodes_abstracted}
            total={counts.nodes_total}
          />
        </Stack>
      )}
      {streamError !== null && <Text c="red">{streamError}</Text>}
      {actionError !== null && <Text c="red">{actionError}</Text>}
    </Stack>
  );
}

export default SyncPanel;
