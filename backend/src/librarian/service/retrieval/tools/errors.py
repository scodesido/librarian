class BudgetExceededError(Exception):
    """The agent tried to descend past its budget. Propagates out of
    `agent.run` so the endpoint can return a 400 — the spec is explicit
    that this is a client-facing error, not something to recover from.
    """


class UnknownBlobIdsError(Exception):
    """Raised by `load_blobs` when one or more requested blob_ids don't exist
    for the user. Wrapped into `ModelRetry` by the in-loop tools; surfaced as
    500 by the endpoint (the final-answer path shouldn't see this normally).
    """

    def __init__(self, missing: list[int]) -> None:
        super().__init__(
            f"blob_id(s) {missing} do not exist or do not belong to this user"
        )
        self.missing = missing
