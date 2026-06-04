import { useEffect, useMemo, useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  PasswordInput,
  Select,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { api } from "../api/client";
import { modelRequiresToken, SLOT_LABELS, SLOTS } from "./slots";
import type { Slot } from "./slots";

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

function formatNumber(n: number): string {
  return n.toLocaleString();
}

function StatusBadge({
  needsToken,
  hasToken,
}: {
  needsToken: boolean;
  hasToken: boolean;
}) {
  if (!needsToken) {
    return (
      <Badge color="gray" variant="light">
        No token needed
      </Badge>
    );
  }
  return hasToken ? (
    <Badge color="green" variant="light">
      Saved
    </Badge>
  ) : (
    <Badge color="orange" variant="light">
      Token required
    </Badge>
  );
}

// One row per slot, marrying the model selection and its API token. The model
// select auto-saves on change (it's a pick-from-a-whitelist setting); the
// token is write-only and committed explicitly. "Copy above" pulls the token
// typed in the row above and saves it here in one click, so the common case —
// one shared key across every slot — is just paste-once-then-copy-down.
function ModelsAndTokensSection({
  catalog,
  models,
  tokens,
  onSaveModel,
  onSaveToken,
  onDeleteToken,
}: {
  catalog: ModelCatalog;
  models: UserModelSettings;
  tokens: Record<Slot, boolean>;
  onSaveModel: (slot: Slot, model: string) => Promise<void>;
  onSaveToken: (slot: Slot, value: string) => Promise<void>;
  onDeleteToken: (slot: Slot) => Promise<void>;
}) {
  // We never read existing token values back from the server (encrypted at
  // rest), so these inputs are write-only. We deliberately keep a typed value
  // after a save so "copy above" further down the column still has a source.
  const [typed, setTyped] = useState<Record<Slot, string>>(
    () => Object.fromEntries(SLOTS.map((s) => [s, ""])) as Record<Slot, string>,
  );
  const [pending, setPending] = useState<Slot | null>(null);
  const [modelSaving, setModelSaving] = useState<Slot | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runWithError = async (slot: Slot, fn: () => Promise<void>) => {
    setPending(slot);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(`${SLOT_LABELS[slot]}: ${(e as Error).message}`);
    } finally {
      setPending(null);
    }
  };

  const onChangeModel = async (slot: Slot, model: string) => {
    setModelSaving(slot);
    setError(null);
    try {
      await onSaveModel(slot, model);
    } catch (e) {
      setError(`${SLOT_LABELS[slot]}: ${(e as Error).message}`);
    } finally {
      setModelSaving(null);
    }
  };

  const onSaveRowToken = (slot: Slot) =>
    runWithError(slot, async () => {
      const value = typed[slot];
      if (value.length === 0) return;
      await onSaveToken(slot, value);
    });

  const onCopyAbove = (from: Slot, to: Slot) =>
    runWithError(to, async () => {
      const value = typed[from];
      if (value.length === 0) {
        setError(
          `Nothing to copy from "${SLOT_LABELS[from]}" — paste a token there first.`,
        );
        return;
      }
      setTyped({ ...typed, [to]: value });
      await onSaveToken(to, value);
    });

  const onDeleteOne = (slot: Slot) =>
    runWithError(slot, () => onDeleteToken(slot));

  return (
    <Card withBorder padding="md">
      <Stack gap="sm">
        <Title order={4}>Models &amp; tokens</Title>
        <Text c="dimmed" size="sm">
          Pick a model for each pipeline step and, for non-Ollama models, paste
          the matching API token. Tokens are encrypted at rest with the
          operator's Fernet key and never returned to the browser. Paste once at
          the top and use "copy above" to reuse the same key down the column.
        </Text>
        <Table verticalSpacing="xs" horizontalSpacing="sm" layout="fixed">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Slot</Table.Th>
              <Table.Th w={200}>Model</Table.Th>
              <Table.Th w={190}>API token</Table.Th>
              <Table.Th w={200} />
              <Table.Th w={130}>Status</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {SLOTS.map((slot, i) => {
              const current = models[slot];
              const needsToken = modelRequiresToken(current);
              const hasToken = tokens[slot];
              const prev = i > 0 ? SLOTS[i - 1] : null;
              return (
                <Table.Tr key={slot}>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {SLOT_LABELS[slot]}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Select
                      size="sm"
                      value={current}
                      onChange={(v) =>
                        v !== null && void onChangeModel(slot, v)
                      }
                      data={catalog[slot].allowed.map((opt) => ({
                        value: opt.model,
                        label: opt.label ?? opt.model,
                      }))}
                      allowDeselect={false}
                      disabled={modelSaving === slot}
                    />
                  </Table.Td>
                  <Table.Td>
                    <PasswordInput
                      size="sm"
                      value={typed[slot]}
                      onChange={(e) =>
                        setTyped({ ...typed, [slot]: e.currentTarget.value })
                      }
                      placeholder={needsToken ? "Paste token" : "Not required"}
                      disabled={!needsToken && !hasToken}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap" justify="flex-end">
                      <Button
                        size="compact-sm"
                        variant="light"
                        onClick={() => onSaveRowToken(slot)}
                        disabled={typed[slot].length === 0 || pending !== null}
                        loading={pending === slot}
                      >
                        Save
                      </Button>
                      <Tooltip
                        label="Copy the token from the row above and save it"
                        disabled={prev === null}
                      >
                        <Button
                          size="compact-sm"
                          variant="subtle"
                          onClick={() => prev && void onCopyAbove(prev, slot)}
                          disabled={prev === null || pending !== null}
                        >
                          Copy above
                        </Button>
                      </Tooltip>
                      <Tooltip label="Remove saved token" disabled={!hasToken}>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label="Remove saved token"
                          onClick={() => onDeleteOne(slot)}
                          disabled={!hasToken || pending !== null}
                          loading={pending === slot}
                        >
                          ✕
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <StatusBadge needsToken={needsToken} hasToken={hasToken} />
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
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

function AccountPanel({ onChanged }: { onChanged?: () => void }) {
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

  const onSaveModel = async (slot: Slot, model: string) => {
    if (me === null) return;
    const next = { ...me.models, [slot]: model };
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
    // Re-fetch the effective settings so the dropdown reflects any server-side
    // fallback (e.g. catalog drift) and the status badge re-evaluates.
    const refreshed = await api("/settings/me");
    if (refreshed.ok) setMe((await refreshed.json()) as MeResponse);
    onChanged?.();
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
    onChanged?.();
  };

  const onDeleteToken = async (slot: Slot) => {
    const resp = await api(`/settings/tokens/${slot}`, { method: "DELETE" });
    if (!resp.ok && resp.status !== 204) {
      throw new Error(`Remove failed (${resp.status})`);
    }
    const refreshed = await api("/settings/tokens");
    if (refreshed.ok) setTokens((await refreshed.json()) as TokensResponse);
    onChanged?.();
  };

  if (loadError !== null) {
    return (
      <Alert color="red" title="Couldn't load account settings">
        {loadError}
      </Alert>
    );
  }

  if (catalog === null || me === null || tokens === null) {
    return <Loader />;
  }

  return (
    <Stack gap="md">
      <ModelsAndTokensSection
        catalog={catalog}
        models={me.models}
        tokens={tokensBySlot}
        onSaveModel={onSaveModel}
        onSaveToken={onSaveToken}
        onDeleteToken={onDeleteToken}
      />
      <UsageSection usage={usage} />
    </Stack>
  );
}

export default AccountPanel;
