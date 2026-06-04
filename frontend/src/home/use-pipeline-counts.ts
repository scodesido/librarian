import { useEffect, useState } from "react";

export interface PipelineCounts {
  files_total: number;
  files_ready: number;
  blobs_total: number;
  blobs_in_tree: number;
  nodes_total: number;
  nodes_weighted: number;
  nodes_abstracted: number;
}

export interface PipelineCountsState {
  counts: PipelineCounts | null;
  streamError: string | null;
}

// Single subscription to the server-sent pipeline counts, owned by HomeScreen.
// Both the Sync panel (progress bars) and the tab-gating logic (is Search
// reachable yet?) read from this one stream rather than each opening its own
// EventSource.
export function usePipelineCounts(): PipelineCountsState {
  const [counts, setCounts] = useState<PipelineCounts | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);

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

  return { counts, streamError };
}

// The "fully synced, ready for retrieval" criterion: every pipeline stage has
// at least one item and has fully processed all of them. Gates the Search tab
// and drives the Sync panel's status badge.
export function syncFullyReady(counts: PipelineCounts | null): boolean {
  return (
    counts !== null &&
    counts.files_total > 0 &&
    counts.files_ready === counts.files_total &&
    counts.blobs_total > 0 &&
    counts.blobs_in_tree === counts.blobs_total &&
    counts.nodes_total > 0 &&
    counts.nodes_abstracted === counts.nodes_total
  );
}
