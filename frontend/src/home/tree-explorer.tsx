import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Group,
  ScrollArea,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { api } from "../api/client";

interface AbstractFields {
  summary?: string;
  topics?: string[];
  intended_audience?: string;
  content_type?: string[];
  domains?: string[];
  running_summary?: string;
}

interface NodeChildView {
  kind: "node";
  node_id: number;
  height: number;
  abstract: AbstractFields | null;
  blob_count: number | null;
}

interface BlobChildView {
  kind: "blob";
  blob_id: number;
  abstract: AbstractFields;
  file_id: number;
  file_blob_index: number;
  file_start: number;
  file_end: number;
}

type ChildView = NodeChildView | BlobChildView;

interface NodeView {
  node_id: number;
  is_root: boolean;
  height: number;
  abstract: AbstractFields | null;
  blob_count: number | null;
  children: ChildView[];
}

function topicsLine(topics: string[] | undefined): string {
  if (topics === undefined || topics.length === 0) return "(no topics yet)";
  return topics.join(" · ");
}

function NodeAbstractView({ view }: { view: NodeView }) {
  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={4}>
            {view.is_root ? "Root" : `Node #${view.node_id}`}
          </Title>
          <Badge variant="light">height {view.height}</Badge>
          {view.blob_count !== null && (
            <Badge variant="light" color="blue">
              {view.blob_count} blob{view.blob_count === 1 ? "" : "s"}
            </Badge>
          )}
        </Group>
      </Group>
      {view.abstract === null ? (
        <Text c="dimmed">No abstract yet (node_extractor hasn't run).</Text>
      ) : (
        <Stack gap={4}>
          {view.abstract.summary !== undefined && (
            <Text>{view.abstract.summary}</Text>
          )}
          <Text size="sm" c="dimmed">
            Topics: {topicsLine(view.abstract.topics)}
          </Text>
          {view.abstract.intended_audience !== undefined && (
            <Text size="sm" c="dimmed">
              Audience: {view.abstract.intended_audience}
            </Text>
          )}
          {view.abstract.content_type !== undefined &&
            view.abstract.content_type.length > 0 && (
              <Text size="sm" c="dimmed">
                Type: {view.abstract.content_type.join(", ")}
              </Text>
            )}
          {view.abstract.domains !== undefined &&
            view.abstract.domains.length > 0 && (
              <Text size="sm" c="dimmed">
                Domains: {view.abstract.domains.join(", ")}
              </Text>
            )}
        </Stack>
      )}
    </Stack>
  );
}

function NodeChildCard({
  child,
  onOpen,
}: {
  child: NodeChildView;
  onOpen: (node_id: number) => void;
}) {
  return (
    <Card
      withBorder
      shadow="xs"
      padding="sm"
      style={{ cursor: "pointer" }}
      onClick={() => onOpen(child.node_id)}
    >
      <Group justify="space-between" align="flex-start">
        <Stack gap={4} style={{ flexGrow: 1 }}>
          <Text fw={500}>{topicsLine(child.abstract?.topics)}</Text>
          <Text size="xs" c="dimmed">
            node #{child.node_id} · height {child.height}
          </Text>
        </Stack>
        <Badge variant="light" color="blue">
          {child.blob_count ?? "?"} blobs
        </Badge>
      </Group>
    </Card>
  );
}

function BlobChildCard({ child }: { child: BlobChildView }) {
  return (
    <Card withBorder shadow="xs" padding="sm">
      <Stack gap={4}>
        <Text fw={500}>{topicsLine(child.abstract.topics)}</Text>
        <Text size="xs" c="dimmed">
          blob #{child.blob_id} · file #{child.file_id} · index{" "}
          {child.file_blob_index} · range [{child.file_start}, {child.file_end})
        </Text>
      </Stack>
    </Card>
  );
}

// Sentinel pushed onto the history stack when the user navigates *from*
// the root: -1 isn't a valid node_id, so "back" decodes it as "return to
// root" (nodeId === null) rather than fetching node #-1.
const ROOT_HISTORY_MARKER = -1;

function TreeExplorer() {
  const [nodeId, setNodeId] = useState<number | null>(null);
  const [history, setHistory] = useState<number[]>([]);
  const [view, setView] = useState<NodeView | null>(null);
  // Start loading=true: the mount-time effect kicks off the initial fetch
  // immediately, so the first render should show "Loading…" rather than
  // an empty panel.
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // All setState calls live inside async callbacks (post-await) or in the
  // event handlers below, never synchronously in the effect body. That
  // keeps React 19's react-hooks/set-state-in-effect rule happy: the
  // effect is purely "subscribe to nodeId changes, fetch in a callback,
  // setState when the callback resolves."
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const path =
          nodeId === null ? "/data/tree/node" : `/data/tree/node/${nodeId}`;
        const resp = await api(path);
        if (cancelled) return;
        if (resp.status === 404) {
          const detail = await resp
            .json()
            .then((b: { detail?: string }) => b.detail)
            .catch(() => undefined);
          setView(null);
          setError(detail ?? "Node not found");
        } else if (!resp.ok) {
          setView(null);
          setError(`Request failed (${resp.status})`);
        } else {
          const data = (await resp.json()) as NodeView;
          setView(data);
          setError(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [nodeId]);

  const onOpenChild = (childId: number) => {
    const currentMarker =
      view !== null && !view.is_root ? view.node_id : ROOT_HISTORY_MARKER;
    setHistory((h) => [...h, currentMarker]);
    setLoading(true);
    setNodeId(childId);
  };

  const onBack = () => {
    if (history.length === 0) return;
    const prev = history[history.length - 1];
    setHistory((h) => h.slice(0, -1));
    setLoading(true);
    setNodeId(prev === ROOT_HISTORY_MARKER ? null : prev);
  };

  const onRoot = () => {
    setHistory([]);
    setLoading(true);
    setNodeId(null);
  };

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Title order={3}>Tree explorer</Title>
        <Group gap="xs">
          <Button
            variant="default"
            size="xs"
            disabled={history.length === 0}
            onClick={onBack}
          >
            ← Back
          </Button>
          <Button variant="default" size="xs" onClick={onRoot}>
            ↑ Root
          </Button>
        </Group>
      </Group>
      {loading && view === null && <Text c="dimmed">Loading…</Text>}
      {error !== null && view === null && <Text c="dimmed">{error}</Text>}
      {view !== null && (
        <Stack gap="md">
          <NodeAbstractView view={view} />
          <Stack gap={4}>
            <Text fw={500}>Children ({view.children.length})</Text>
            <ScrollArea.Autosize mah={420}>
              <Stack gap="xs">
                {view.children.length === 0 && (
                  <Text c="dimmed">No children yet.</Text>
                )}
                {view.children.map((child) =>
                  child.kind === "node" ? (
                    <NodeChildCard
                      key={`n-${child.node_id}`}
                      child={child}
                      onOpen={onOpenChild}
                    />
                  ) : (
                    <BlobChildCard key={`b-${child.blob_id}`} child={child} />
                  ),
                )}
              </Stack>
            </ScrollArea.Autosize>
          </Stack>
        </Stack>
      )}
    </Stack>
  );
}

export default TreeExplorer;
