from datetime import datetime

from librarian.db.table import Table, TableModel


class OAuthClientModel(TableModel):
    """Row shape for the `oauth_clients` table — one MCP client (e.g.
    claude.ai) that has called /register.

    Maps onto the SDK's `OAuthClientInformationFull` round-trip: the fields
    we persist are the ones load-bearing for the flow (redirect_uris for
    matching, client_name for the consent screen, grant/response types and
    auth method for protocol echoing). The richer optional metadata from
    RFC 7591 (logo_uri, tos_uri, …) is intentionally dropped; we can add
    columns later if a use case needs them.
    """

    client_id: str
    client_name: str
    redirect_uris: list[str]
    scopes: list[str]
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: str
    created_at: datetime


class OAuthClients(Table):
    async def get(self, client_id: str) -> OAuthClientModel | None:
        record = await self.conn.fetchrow(
            (
                "SELECT client_id, client_name, redirect_uris, scopes, "
                "grant_types, response_types, token_endpoint_auth_method, "
                "created_at FROM oauth_clients WHERE client_id = $1"
            ),
            client_id,
        )
        return OAuthClientModel.from_record(record)

    async def register(
        self,
        client_id: str,
        client_name: str,
        redirect_uris: list[str],
        scopes: list[str],
        grant_types: list[str],
        response_types: list[str],
        token_endpoint_auth_method: str,
    ) -> None:
        await self.conn.execute(
            (
                "INSERT INTO oauth_clients "
                "(client_id, client_name, redirect_uris, scopes, "
                "grant_types, response_types, token_endpoint_auth_method) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)"
            ),
            client_id,
            client_name,
            redirect_uris,
            scopes,
            grant_types,
            response_types,
            token_endpoint_auth_method,
        )
