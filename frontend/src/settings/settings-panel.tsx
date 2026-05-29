import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  PasswordInput,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { api } from "../api/client";

// Slot names mirror the backend Literal in common/settings/model_catalog.py.
// Hard-coded rather than fetched so the UI can render a stable layout even
// while the catalog request is in flight.
const SLOTS = [
  "blob_llm",
  "node_llm_leaf",
  "node_llm_internal",
  "retrieval_llm",
  "extract_llm",
  "embedding",
] as const;
type Slot = (typeof SLOTS)[number];

const SLOT_LABELS: Record<Slot, string> = {
  blob_llm: "Blob extractor (main + tagging)",
  node_llm_leaf: "Node extractor — leaf nodes",
  node_llm_internal: "Node extractor — internal nodes",
  retrieval_llm: "Retrieval agent",
  extract_llm: "Search-terms extractor",
  embedding: "Embedder",
};

const OPERATION_LABELS: Record<string, string> = {
  blob_extract: "Blob extract",
  blob_tag: "Blob tag",
  node_extract_leaf: "Node extract (leaf)",
  node_extract_internal: "Node extract (internal)",
  retrieval: "Retrieval",
  extract_search_terms: "Search-terms extraction",
  embed_blob: "Blob embedding",
  embed_query: "Query embedding",
};

interface ModelOption {
  model: string;
  label: string | null;
}

interface SlotCatalog {
  allowed: ModelOption[];
  default: string;
}

type ModelCatalog = Record<Slot, SlotCatalog>;

type UserModelSettings = Record<Slot, string>;

interface MeResponse {
  models: UserModelSettings;
}

interface SlotStatus {
  slot: Slot;
  has_token: boolean;
}

interface TokensResponse {
  slots: SlotStatus[];
}

interface UsageAggregate {
  operation: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  call_count: number;
}

interface UsageResponse {
  since: string;
  aggregates: UsageAggregate[];
}

// "<provider>:..." → provider. Mirrors common/settings/model_catalog.py's
// `requires_token`: ollama is the only provider that runs without one.
function providerOf(model: string): string {
  const idx = model.indexOf(":");
  return idx === -1 ? model : model.slice(0, idx);
}

function modelRequiresToken(model: string): boolean {
  return providerOf(model) !== "ollama";
}

function formatNumber(n: number): string {
  return n.toLocaleString();
}

function CatalogSection({
  catalog,
  models,
  tokens,
  onSave,
}: {
  catalog: ModelCatalog;
  models: UserModelSettings;
  tokens: Record<Slot, boolean>;
  onSave: (next: UserModelSettings) => Promise<void>;
}) {
  const [draft, setDraft] = useState<UserModelSettings>(models);
  const [seenModels, setSeenModels] = useState<UserModelSettings>(models);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-sync the draft when the parent reloads (e.g. after a successful
  // save returns fresh effective values from the server). React's canonical
  // "reset state on prop change" pattern: compare current prop to a tracked
  // previous, update both during render. Avoids the cascading-render trap
  // of doing setDraft(models) inside an effect.
  if (seenModels !== models) {
    setSeenModels(models);
    setDraft(models);
  }

  const dirty = SLOTS.some((s) => draft[s] !== models[s]);

  const onSubmit = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(draft);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card withBorder padding="md">
      <Stack gap="sm">
        <Title order={4}>Models</Title>
        <Text c="dimmed" size="sm">
          Pick which model each pipeline step uses. Options come from the
          operator's whitelist. Slots that resolve to a non-Ollama model need a
          matching API token (see below).
        </Text>
        {SLOTS.map((slot) => {
          const slotCatalog = catalog[slot];
          const current = draft[slot];
          const needsToken = modelRequiresToken(current);
          const hasToken = tokens[slot];
          return (
            <Stack key={slot} gap={4}>
              <Group justify="space-between" align="flex-end">
                <Text fw={500} size="sm">
                  {SLOT_LABELS[slot]}
                </Text>
                <Select
                  value={current}
                  onChange={(v) =>
                    v !== null && setDraft({ ...draft, [slot]: v })
                  }
                  data={slotCatalog.allowed.map((opt) => ({
                    value: opt.model,
                    label: opt.label ?? opt.model,
                  }))}
                  allowDeselect={false}
                  style={{ minWidth: 320 }}
                />
              </Group>
              {needsToken && !hasToken && (
                <Text size="xs" c="orange">
                  Requires a {providerOf(current)} API token — not yet saved.
                </Text>
              )}
            </Stack>
          );
        })}
        {error !== null && (
          <Text c="red" size="sm">
            {error}
          </Text>
        )}
        <Group justify="flex-end">
          <Button
            onClick={onSubmit}
            disabled={!dirty || saving}
            loading={saving}
          >
            Save models
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}

function TokensSection({
  tokens,
  onSaveToken,
  onDeleteToken,
}: {
  tokens: Record<Slot, boolean>;
  onSaveToken: (slot: Slot, value: string) => Promise<void>;
  onDeleteToken: (slot: Slot) => Promise<void>;
}) {
  // typed[slot] is the value the user typed into slot's input box. We
  // never read existing values from the server (encrypted-at-rest), so
  // the inputs are write-only.
  const [typed, setTyped] = useState<Record<Slot, string>>(
    () => Object.fromEntries(SLOTS.map((s) => [s, ""])) as Record<Slot, string>,
  );
  const [pending, setPending] = useState<Slot | null>(null);
  const [error, setError] = useState<string | null>(null);
  // "Same value for all" mode: when on, one input drives every slot's
  // save. Defaults on — the common case is one API key shared across
  // all LLM slots, which the user asked us to make frictionless. Once
  // a user has explicit per-slot tokens, untoggle for individual control.
  const [shared, setShared] = useState(true);
  const [sharedValue, setSharedValue] = useState("");

  const runWithError = async (slot: Slot, fn: () => Promise<void>) => {
    setPending(slot);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(`${slot}: ${(e as Error).message}`);
    } finally {
      setPending(null);
    }
  };

  const onSaveOne = (slot: Slot) =>
    runWithError(slot, async () => {
      const value = typed[slot];
      if (value.length === 0) return;
      await onSaveToken(slot, value);
      setTyped({ ...typed, [slot]: "" });
    });

  const onDeleteOne = (slot: Slot) =>
    runWithError(slot, () => onDeleteToken(slot));

  const onApplyShared = async () => {
    if (sharedValue.length === 0) return;
    setError(null);
    for (const slot of SLOTS) {
      try {
        setPending(slot);
        await onSaveToken(slot, sharedValue);
      } catch (e) {
        setError(`${slot}: ${(e as Error).message}`);
        setPending(null);
        return;
      }
    }
    setPending(null);
    setSharedValue("");
  };

  return (
    <Card withBorder padding="md">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>API tokens</Title>
          <Switch
            label="Use one value for all slots"
            checked={shared}
            onChange={(e) => setShared(e.currentTarget.checked)}
          />
        </Group>
        <Text c="dimmed" size="sm">
          Tokens are encrypted at rest with the operator's Fernet key. Saved
          values are never returned to the browser; this UI is write-only.
        </Text>
        {shared ? (
          <Stack gap="xs">
            <PasswordInput
              label="Same token for every slot"
              placeholder="Paste your API key once and apply to all slots"
              value={sharedValue}
              onChange={(e) => setSharedValue(e.currentTarget.value)}
            />
            <Group justify="flex-end">
              <Button
                onClick={onApplyShared}
                disabled={sharedValue.length === 0 || pending !== null}
                loading={pending !== null}
              >
                Apply to all slots
              </Button>
            </Group>
            <Divider label="Current status" labelPosition="left" />
            <Stack gap={4}>
              {SLOTS.map((slot) => (
                <Group key={slot} justify="space-between">
                  <Text size="sm">{SLOT_LABELS[slot]}</Text>
                  <Group gap="xs">
                    <Badge
                      color={tokens[slot] ? "green" : "gray"}
                      variant="light"
                    >
                      {tokens[slot] ? "Saved" : "Not saved"}
                    </Badge>
                    {tokens[slot] && (
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        color="red"
                        onClick={() => onDeleteOne(slot)}
                        loading={pending === slot}
                      >
                        Remove
                      </Button>
                    )}
                  </Group>
                </Group>
              ))}
            </Stack>
          </Stack>
        ) : (
          <Stack gap="xs">
            {SLOTS.map((slot) => (
              <Stack key={slot} gap={2}>
                <Group justify="space-between" align="flex-end">
                  <Text size="sm" fw={500}>
                    {SLOT_LABELS[slot]}
                  </Text>
                  <Badge
                    color={tokens[slot] ? "green" : "gray"}
                    variant="light"
                  >
                    {tokens[slot] ? "Saved" : "Not saved"}
                  </Badge>
                </Group>
                <Group align="flex-end" gap="xs">
                  <PasswordInput
                    value={typed[slot]}
                    onChange={(e) =>
                      setTyped({ ...typed, [slot]: e.currentTarget.value })
                    }
                    placeholder="Paste a new value to overwrite"
                    style={{ flexGrow: 1 }}
                  />
                  <Button
                    onClick={() => onSaveOne(slot)}
                    disabled={typed[slot].length === 0 || pending !== null}
                    loading={pending === slot}
                  >
                    Save
                  </Button>
                  <Button
                    variant="subtle"
                    color="red"
                    onClick={() => onDeleteOne(slot)}
                    disabled={!tokens[slot] || pending !== null}
                    loading={pending === slot}
                  >
                    Remove
                  </Button>
                </Group>
              </Stack>
            ))}
          </Stack>
        )}
        {error !== null && (
          <Text c="red" size="sm">
            {error}
          </Text>
        )}
      </Stack>
    </Card>
  );
}

function UsageSection({ usage }: { usage: UsageResponse | null }) {
  const since = usage === null ? null : new Date(usage.since);
  return (
    <Card withBorder padding="md">
      <Stack gap="sm">
        <Title order={4}>Token usage</Title>
        <Text c="dimmed" size="sm">
          {since === null
            ? "Loading…"
            : `Per-(operation, model) totals since ${since.toLocaleDateString()}.`}
        </Text>
        {usage !== null && usage.aggregates.length === 0 && (
          <Text c="dimmed">No usage recorded in this window.</Text>
        )}
        {usage !== null && usage.aggregates.length > 0 && (
          <Table withTableBorder withColumnBorders striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Operation</Table.Th>
                <Table.Th>Model</Table.Th>
                <Table.Th style={{ textAlign: "right" }}>Calls</Table.Th>
                <Table.Th style={{ textAlign: "right" }}>Input tokens</Table.Th>
                <Table.Th style={{ textAlign: "right" }}>
                  Output tokens
                </Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {usage.aggregates.map((a, i) => (
                <Table.Tr key={`${a.operation}-${a.model}-${i}`}>
                  <Table.Td>
                    {OPERATION_LABELS[a.operation] ?? a.operation}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" ff="monospace">
                      {a.model}
                    </Text>
                  </Table.Td>
                  <Table.Td style={{ textAlign: "right" }}>
                    {formatNumber(a.call_count)}
                  </Table.Td>
                  <Table.Td style={{ textAlign: "right" }}>
                    {formatNumber(a.input_tokens)}
                  </Table.Td>
                  <Table.Td style={{ textAlign: "right" }}>
                    {formatNumber(a.output_tokens)}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Card>
  );
}

function SettingsPanel() {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [tokens, setTokens] = useState<TokensResponse | null>(null);
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    // Cancellation guard: a fast tab-switch could unmount us before the
    // fetches resolve. Without the guard, the late setState would warn
    // (and on dev mode trigger the strict-mode double-mount cascade).
    let cancelled = false;
    const load = async () => {
      try {
        const [c, m, t, u] = await Promise.all([
          api("/settings/catalog"),
          api("/settings/me"),
          api("/settings/tokens"),
          api("/settings/usage"),
        ]);
        if (cancelled) return;
        if (!c.ok || !m.ok || !t.ok || !u.ok) {
          throw new Error(
            `Failed to load settings (catalog ${c.status}, me ${m.status}, ` +
              `tokens ${t.status}, usage ${u.status})`,
          );
        }
        const [cBody, mBody, tBody, uBody] = await Promise.all([
          c.json() as Promise<ModelCatalog>,
          m.json() as Promise<MeResponse>,
          t.json() as Promise<TokensResponse>,
          u.json() as Promise<UsageResponse>,
        ]);
        if (cancelled) return;
        setCatalog(cBody);
        setMe(mBody);
        setTokens(tBody);
        setUsage(uBody);
      } catch (e) {
        if (cancelled) return;
        setLoadError((e as Error).message);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const tokensBySlot: Record<Slot, boolean> = useMemo(() => {
    const empty = Object.fromEntries(SLOTS.map((s) => [s, false])) as Record<
      Slot,
      boolean
    >;
    if (tokens === null) return empty;
    for (const row of tokens.slots) empty[row.slot] = row.has_token;
    return empty;
  }, [tokens]);

  const onSaveModels = async (next: UserModelSettings) => {
    const resp = await api("/settings/me", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(next),
    });
    if (!resp.ok) {
      const detail = await resp
        .json()
        .then((b: { detail?: string }) => b.detail)
        .catch(() => undefined);
      throw new Error(detail ?? `Save failed (${resp.status})`);
    }
    // Re-fetch the effective settings so the dropdowns reflect any
    // server-side fallback (e.g. catalog drift) and so the warning
    // banner re-evaluates against the now-fresh tokens.
    const refreshed = await api("/settings/me");
    if (refreshed.ok) setMe((await refreshed.json()) as MeResponse);
  };

  const onSaveToken = async (slot: Slot, value: string) => {
    const resp = await api(`/settings/tokens/${slot}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: value }),
    });
    if (!resp.ok) {
      const detail = await resp
        .json()
        .then((b: { detail?: string }) => b.detail)
        .catch(() => undefined);
      throw new Error(detail ?? `Save failed (${resp.status})`);
    }
    const refreshed = await api("/settings/tokens");
    if (refreshed.ok) setTokens((await refreshed.json()) as TokensResponse);
  };

  const onDeleteToken = async (slot: Slot) => {
    const resp = await api(`/settings/tokens/${slot}`, { method: "DELETE" });
    if (!resp.ok && resp.status !== 204) {
      throw new Error(`Remove failed (${resp.status})`);
    }
    const refreshed = await api("/settings/tokens");
    if (refreshed.ok) setTokens((await refreshed.json()) as TokensResponse);
  };

  if (loadError !== null) {
    return (
      <Alert color="red" title="Couldn't load settings">
        {loadError}
      </Alert>
    );
  }

  if (catalog === null || me === null || tokens === null) {
    return <Loader />;
  }

  return (
    <Stack gap="md">
      <TokensSection
        tokens={tokensBySlot}
        onSaveToken={onSaveToken}
        onDeleteToken={onDeleteToken}
      />
      <CatalogSection
        catalog={catalog}
        models={me.models}
        tokens={tokensBySlot}
        onSave={onSaveModels}
      />
      <UsageSection usage={usage} />
    </Stack>
  );
}

export default SettingsPanel;
