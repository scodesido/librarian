import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  Code,
  Group,
  ScrollArea,
  Spoiler,
  Stack,
  Text,
  Textarea,
  Timeline,
  Title,
} from "@mantine/core";

const QUESTION_STORAGE_KEY = "librarian.search_question";
// Mirrors backend QuerySettings.question_max_chars. Kept in sync by hand
// for now — bump both sides if the question budget grows.
const QUESTION_MAX_CHARS = 1000;

interface AbstractFields {
  summary?: string;
  title?: string;
  topics?: string[];
  intended_audience?: string;
  content_type?: string[];
  domains?: string[];
}

interface BlobResult {
  blob_id: number;
  file_id: number;
  file_path: string;
  file_start: number;
  file_end: number;
  abstract: AbstractFields;
  content: string;
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

interface ExpandedNode {
  node_id: number;
  children: ChildView[];
}

interface ExpandEvent {
  kind: "expand";
  step: number;
  budget: number;
  requested_node_ids: number[];
  expanded: ExpandedNode[];
}

interface FetchEvent {
  kind: "fetch";
  blob_ids: number[];
}

interface DoneEvent {
  kind: "done";
  blobs: BlobResult[];
  visited_node_ids: number[];
  steps: number;
  rationale: string;
}

interface ErrorEvent {
  kind: "error";
  detail: string;
}

type QueryEvent = ExpandEvent | FetchEvent | DoneEvent | ErrorEvent;

function topicsLine(topics: string[] | undefined): string {
  if (topics === undefined || topics.length === 0) return "(no topics)";
  return topics.join(" · ");
}

function ExpandTimelineItem({ event }: { event: ExpandEvent }) {
  return (
    <Timeline.Item
      title={`Step ${event.step}/${event.budget} — expanded ${event.requested_node_ids.length} node(s)`}
    >
      <Stack gap={4}>
        {event.expanded.map((node) => (
          <Text size="sm" key={node.node_id} c="dimmed">
            node #{node.node_id} →{" "}
            {node.children.length === 0
              ? "(no children)"
              : node.children
                  .slice(0, 5)
                  .map((c) =>
                    c.kind === "node"
                      ? `node #${c.node_id} [${topicsLine(c.abstract?.topics)}]`
                      : `blob #${c.blob_id} [${topicsLine(c.abstract.topics)}]`,
                  )
                  .join(" · ")}
            {node.children.length > 5 && " · …"}
          </Text>
        ))}
      </Stack>
    </Timeline.Item>
  );
}

function FetchTimelineItem({ event }: { event: FetchEvent }) {
  return (
    <Timeline.Item title={`Peeked at ${event.blob_ids.length} blob content(s)`}>
      <Text size="sm" c="dimmed">
        blob_ids: {event.blob_ids.join(", ")}
      </Text>
    </Timeline.Item>
  );
}

function BlobResultCard({ blob }: { blob: BlobResult }) {
  const range = `[${blob.file_start}, ${blob.file_end})`;
  return (
    <Card withBorder shadow="xs" padding="md">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Text fw={500}>
              {blob.abstract.title ?? `blob #${blob.blob_id}`}
            </Text>
            <Text size="xs" c="dimmed">
              blob #{blob.blob_id} · file #{blob.file_id} · range {range}
            </Text>
          </Stack>
          <Badge variant="light">{topicsLine(blob.abstract.topics)}</Badge>
        </Group>
        {blob.abstract.summary !== undefined && (
          <Text size="sm">{blob.abstract.summary}</Text>
        )}
        <Spoiler maxHeight={80} showLabel="Show content" hideLabel="Hide">
          <Code block style={{ whiteSpace: "pre-wrap" }}>
            {blob.content}
          </Code>
        </Spoiler>
      </Stack>
    </Card>
  );
}

// Parse a single SSE block ("event: X\ndata: {...}") into the typed event.
// The `kind` discriminator lives inside the JSON payload too, so we don't
// need to read the `event:` line — we just need the `data:` line.
function parseSseBlock(block: string): QueryEvent | null {
  for (const line of block.split("\n")) {
    if (!line.startsWith("data:")) continue;
    try {
      return JSON.parse(line.slice(5).trim()) as QueryEvent;
    } catch {
      return null;
    }
  }
  return null;
}

function SearchPanel() {
  const [question, setQuestion] = useState<string>(
    () => localStorage.getItem(QUESTION_STORAGE_KEY) ?? "",
  );
  const [searching, setSearching] = useState(false);
  const [events, setEvents] = useState<QueryEvent[]>([]);
  const [done, setDone] = useState<DoneEvent | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onQuestionChange = (value: string) => {
    setQuestion(value);
    localStorage.setItem(QUESTION_STORAGE_KEY, value);
  };

  const onSearch = async () => {
    if (question.trim().length === 0) return;
    setSearching(true);
    setEvents([]);
    setDone(null);
    setError(null);
    try {
      const resp = await fetch(`${API_URL}/data/query/stream`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!resp.ok || resp.body === null) {
        const detail = await resp
          .json()
          .then((b: { detail?: string }) => b.detail)
          .catch(() => undefined);
        setError(detail ?? `Search failed (${resp.status})`);
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      // Keep pulling from the stream until the server closes it. SSE blocks
      // are separated by "\n\n"; we keep the trailing partial block in the
      // buffer between reads.
      while (true) {
        const { value, done: readerDone } = await reader.read();
        if (readerDone) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          if (block.startsWith(":")) continue; // heartbeat
          const parsed = parseSseBlock(block);
          if (parsed === null) continue;
          if (parsed.kind === "done") {
            setDone(parsed);
          } else if (parsed.kind === "error") {
            setError(parsed.detail);
          } else {
            setEvents((prev) => [...prev, parsed]);
          }
        }
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSearching(false);
    }
  };

  return (
    <Stack gap="md">
      <Stack gap="xs">
        <Title order={3}>Search your library</Title>
        <Textarea
          placeholder="Ask anything about your synced documents…"
          value={question}
          onChange={(e) => onQuestionChange(e.currentTarget.value)}
          autosize
          minRows={2}
          maxRows={6}
          maxLength={QUESTION_MAX_CHARS}
        />
        <Group justify="space-between">
          <Text size="xs" c="dimmed">
            {question.length} / {QUESTION_MAX_CHARS}
          </Text>
          <Button
            onClick={onSearch}
            loading={searching}
            disabled={question.trim().length === 0}
          >
            Search
          </Button>
        </Group>
      </Stack>

      {error !== null && (
        <Text c="red" size="sm">
          {error}
        </Text>
      )}

      {events.length > 0 && (
        <Stack gap="xs">
          <Text fw={500} size="sm">
            Exploration trace
          </Text>
          <ScrollArea.Autosize mah={280}>
            <Timeline active={events.length} bulletSize={16} lineWidth={2}>
              {events.map((ev, idx) =>
                ev.kind === "expand" ? (
                  <ExpandTimelineItem key={idx} event={ev} />
                ) : ev.kind === "fetch" ? (
                  <FetchTimelineItem key={idx} event={ev} />
                ) : null,
              )}
            </Timeline>
          </ScrollArea.Autosize>
        </Stack>
      )}

      {done !== null && (
        <Stack gap="xs">
          <Group justify="space-between">
            <Text fw={500}>
              Results ({done.blobs.length} blob
              {done.blobs.length === 1 ? "" : "s"})
            </Text>
            <Text size="xs" c="dimmed">
              {done.steps} step{done.steps === 1 ? "" : "s"} ·{" "}
              {done.visited_node_ids.length} node
              {done.visited_node_ids.length === 1 ? "" : "s"} visited
            </Text>
          </Group>
          {done.rationale.length > 0 && (
            <Text size="sm" c="dimmed" fs="italic">
              {done.rationale}
            </Text>
          )}
          {done.blobs.length === 0 && (
            <Text c="dimmed">
              The agent did not find any relevant blobs in this library.
            </Text>
          )}
          {done.blobs.map((blob) => (
            <BlobResultCard key={blob.blob_id} blob={blob} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

export default SearchPanel;
