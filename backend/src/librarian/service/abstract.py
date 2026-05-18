from pydantic import BaseModel


class Abstract(BaseModel):
    """Per-node/per-blob structured summary. The base shape (no
    running_summary) is what node_extractor produces for internal nodes,
    where there's no notion of a rolling chain.
    """

    summary: str
    topics: list[str]
    intended_audience: str
    content_type: list[str]
    domains: list[str]


class RollingAbstract(Abstract):
    """blob_extractor's per-blob Abstract: the base fields plus a
    running_summary that the LLM weaves into the previous blob's
    running_summary, anchoring the chain across one file's blobs.

    The default empty string lets a base Abstract JSON validate as a
    RollingAbstract — useful when a consumer wants one uniform shape
    regardless of whether the row came from data_blobs or
    data_node_abstracts.
    """

    running_summary: str = ""
