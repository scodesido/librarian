import { useEffect, useState } from "react";
import { Badge, Group, Stack, Text } from "@mantine/core";
import { api } from "../api/client";

interface WorkerEvent {
  event_id: number;
  code: number;
  source: string;
  detail: string | null;
  context: Record<string, unknown> | null;
  created_at: string;
}

interface EventCount {
  code: number;
  count: number;
  latest_at: string;
}

// Events are episodic, so a short poll is enough — unlike the pipeline
// counts, which tick continuously and justify their SSE stream.
const POLL_INTERVAL_MS = 10_000;

const CODE_LABELS: Record<number, string> = {
  1001: "File processed",
  1002: "Library ready",
  2001: "Internal error",
  2002: "Pipeline error",
  3001: "Provider rate-limited",
  3002: "Provider unavailable",
  4001: "Missing API token",
  4002: "Invalid or expired token",
  4003: "Google Drive access needed",
};

// Category = code // 1000. 2xxx and 4xxx are both "bad" (red), but only
// 4xxx is the user's to fix — surfaced as a per-event hint below.
const CATEGORY_COLOR: Record<number, string> = {
  1: "green",
  2: "red",
  3: "yellow",
  4: "red",
};
const CATEGORY_LABEL: Record<number, string> = {
  1: "Info",
  2: "Internal",
  3: "Provider",
  4: "Action needed",
};

function category(code: number): number {
  return Math.floor(code / 1000);
}

function codeLabel(code: number): string {
  return CODE_LABELS[code] ?? `Code ${code}`;
}

function EventRow({ event }: { event: WorkerEvent }) {
  const cat = category(event.code);
  const when = new Date(event.created_at).toLocaleString();
  return (
    <Group gap="xs" wrap="nowrap" align="flex-start">
      <Badge color={CATEGORY_COLOR[cat]} variant="light" size="sm">
        {codeLabel(event.code)}
      </Badge>
      <Stack gap={0} style={{ flexGrow: 1 }}>
        <Text size="sm">{event.detail ?? codeLabel(event.code)}</Text>
        <Text size="xs" c="dimmed">
          {event.source} · {when}
          {cat === 4 ? " · Fix it in the Settings tab" : ""}
        </Text>
      </Stack>
    </Group>
  );
}

function WorkerEvents() {
  const [counts, setCounts] = useState<EventCount[]>([]);
  const [events, setEvents] = useState<WorkerEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [countsResp, recentResp] = await Promise.all([
          api("/messages/counts"),
          api("/messages/recent?limit=50"),
        ]);
        if (!countsResp.ok || !recentResp.ok) {
          if (!cancelled) setError("Could not load worker activity");
          return;
        }
        const countsBody = (await countsResp.json()) as {
          counts: EventCount[];
        };
        const recentBody = (await recentResp.json()) as {
          events: WorkerEvent[];
        };
        if (!cancelled) {
          setCounts(countsBody.counts);
          setEvents(recentBody.events);
          setError(null);
        }
      } catch {
        if (!cancelled) setError("Could not load worker activity");
      }
    };
    void load();
    const id = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Fold per-code counts into the four bands for the summary badges.
  const byCategory = new Map<number, number>();
  for (const c of counts) {
    const cat = category(c.code);
    byCategory.set(cat, (byCategory.get(cat) ?? 0) + c.count);
  }
  const categories = [...byCategory.entries()].sort((a, b) => a[0] - b[0]);

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Text fw={500}>Worker activity</Text>
        {categories.length > 0 && (
          <Group gap="xs">
            {categories.map(([cat, n]) => (
              <Badge key={cat} color={CATEGORY_COLOR[cat]} variant="light">
                {CATEGORY_LABEL[cat]}: {n}
              </Badge>
            ))}
          </Group>
        )}
      </Group>
      {error !== null && <Text c="red">{error}</Text>}
      {events.length === 0 ? (
        <Text c="dimmed" size="sm">
          No recent worker events.
        </Text>
      ) : (
        <Stack gap={4}>
          {events.map((event) => (
            <EventRow key={event.event_id} event={event} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

export default WorkerEvents;
