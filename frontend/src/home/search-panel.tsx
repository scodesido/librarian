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

// The whole of what the backend exposes about a node/blob the agent touched
// mid-walk: a display title and its flat tag list. No ids, no scores.
interface Brief {
  title: string | null;
  tags: string[];
}

// One selected fragment. The webapp always queries in text mode, so `content`
// is plaintext and `encoding` is "text"; the binary fields exist only for
// API/MCP callers.
interface ResultBlob {
  title: string | null;
  file_name: string;
  tags: string[];
  mime_type: string;
  content: string;
  encoding: "text" | "base64";
}

interface TermsEvent {
  kind: "terms";
  effective_search_terms: string;
  extracted: boolean;
}

interface ProgressEvent {
  kind: "progress";
  action: "descend" | "detail" | "peek" | "file";
  items: Brief[];
  step: number | null;
  budget: number | null;
}

interface DoneEvent {
  kind: "done";
  rationale: string;
  effective_search_terms: string;
  blobs: ResultBlob[];
}

interface ErrorEvent {
  kind: "error";
  detail: string;
}

type QueryEvent = TermsEvent | ProgressEvent | DoneEvent | ErrorEvent;

const PROGRESS_VERBS: Record<ProgressEvent["action"], string> = {
  descend: "Descended into",
  detail: "Inspected node",
  peek: "Peeked at",
  file: "Listed file fragments",
};

function Tags({ tags }: { tags: string[] }) {
  if (tags.length === 0) return null;
  return (
    <Group gap={4}>
      {tags.map((tag) => (
        <Badge key={tag} variant="light" size="sm">
          {tag}
        </Badge>
      ))}
    </Group>
  );
}

function briefLabel(item: Brief): string {
  return item.title ?? "(untitled)";
}

function TermsTimelineItem({ event }: { event: TermsEvent }) {
  return (
    <Timeline.Item
      title={
        event.extracted
          ? "Extracted search terms"
          : "Using provided search terms"
      }
    >
      <Text size="sm" c="dimmed" style={{ fontStyle: "italic" }}>
        {event.effective_search_terms}
      </Text>
    </Timeline.Item>
  );
}

function progressTitle(event: ProgressEvent): string {
  if (event.action === "descend" && event.step !== null) {
    return `Step ${event.step}/${event.budget} — descended into ${event.items.length} node(s)`;
  }
  return `${PROGRESS_VERBS[event.action]} (${event.items.length})`;
}

function ProgressTimelineItem({ event }: { event: ProgressEvent }) {
  return (
    <Timeline.Item title={progressTitle(event)}>
      <Stack gap={4}>
        {event.items.map((item, idx) => (
          <Group key={idx} gap="xs" wrap="nowrap">
            <Text size="sm" c="dimmed">
              {briefLabel(item)}
            </Text>
            <Tags tags={item.tags} />
          </Group>
        ))}
      </Stack>
    </Timeline.Item>
  );
}

function BlobResultCard({ blob }: { blob: ResultBlob }) {
  return (
    <Card withBorder shadow="xs" padding="md">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Text fw={500}>{blob.title ?? "(untitled)"}</Text>
            <Text size="xs" c="dimmed">
              {blob.file_name}
            </Text>
          </Stack>
          <Tags tags={blob.tags} />
        </Group>
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
                ev.kind === "terms" ? (
                  <TermsTimelineItem key={idx} event={ev} />
                ) : ev.kind === "progress" ? (
                  <ProgressTimelineItem key={idx} event={ev} />
                ) : null,
              )}
            </Timeline>
          </ScrollArea.Autosize>
        </Stack>
      )}

      {done !== null && (
        <Stack gap="xs">
          <Text fw={500}>
            Results ({done.blobs.length} blob
            {done.blobs.length === 1 ? "" : "s"})
          </Text>
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
          {done.blobs.map((blob, idx) => (
            <BlobResultCard key={idx} blob={blob} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

export default SearchPanel;
