// Slot identifiers mirror the backend Literal in
// common/settings/model_catalog.py. Hard-coded (rather than derived from the
// catalog response) so the Account UI can render a stable layout while the
// catalog request is still in flight. Shared by the Account panel and the
// tab-gating readiness hook, which both reason about which slots need a token.
export const SLOTS = [
  "blob_llm",
  "node_llm_leaf",
  "node_llm_internal",
  "retrieval_llm",
  "extract_llm",
  "embedding",
] as const;

export type Slot = (typeof SLOTS)[number];

export const SLOT_LABELS: Record<Slot, string> = {
  blob_llm: "Blob extractor (main + tagging)",
  node_llm_leaf: "Node extractor — leaf nodes",
  node_llm_internal: "Node extractor — internal nodes",
  retrieval_llm: "Retrieval agent",
  extract_llm: "Search-terms extractor",
  embedding: "Embedder",
};

// "<provider>:..." → provider. Mirrors model_catalog.py's `requires_token`:
// ollama is the only provider that runs without an API token.
export function providerOf(model: string): string {
  const idx = model.indexOf(":");
  return idx === -1 ? model : model.slice(0, idx);
}

export function modelRequiresToken(model: string): boolean {
  return providerOf(model) !== "ollama";
}
