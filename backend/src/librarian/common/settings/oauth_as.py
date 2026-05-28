from pydantic import AnyHttpUrl, BaseModel


class OAuthASSettings(BaseModel):
    """OAuth 2.1 authorization server settings — for the AS layer that
    fronts the MCP endpoint (`13.mcp_oauth.md`).

    `public_base_url` is the externally-visible origin
    (`scheme://host[:port]`) the AS metadata documents advertise as the
    issuer and that the MCP SDK uses to compose endpoint URLs
    (`str(issuer_url).rstrip("/") + "/authorize"` etc.). The SDK reads
    nothing from `X-Forwarded-*` (upstream issue #242), so this must be
    set explicitly rather than derived from the request. Must be HTTPS
    for non-loopback issuers per OAuth 2.1.

    Note: this origin must own its host's root — RFC 8414 §3 and RFC
    9728 pin the metadata documents at `/.well-known/oauth-*` regardless
    of any issuer path, so librarian cannot be mounted under a
    reverse-proxy path prefix.
    """

    # Public origin claude.ai (and other MCP clients) reach us at, e.g.
    # https://librarian.example.com or https://test.anaxa.ch:8443.
    # Required — no sensible default for a public-facing AS.
    public_base_url: AnyHttpUrl

    # The single scope this AS issues for MCP access. Declared once here so
    # the registration metadata, the `required_scopes` enforcement on /mcp,
    # and the consent page all read from the same place.
    mcp_scope: str = "mcp:read"

    # How long a `pending`/`granted` authorization grant lives before it
    # expires. Short — the user is expected to consent within minutes of
    # the MCP client redirecting them here.
    authorization_grant_ttl_seconds: int = 600

    # Access-token lifetime. Long, per the "long-lived revocable" decision
    # — 30 days. Tokens are opaque and stored hashed, so revocation is a
    # single DELETE.
    access_token_ttl_seconds: int = 30 * 24 * 3600

    # Refresh-token lifetime. Longer than access tokens but still bounded
    # so a forgotten device cannot retain access forever.
    refresh_token_ttl_seconds: int = 90 * 24 * 3600

    @property
    def mcp_resource_url(self) -> AnyHttpUrl:
        """Public URL of the MCP endpoint, used both as the OAuth resource
        identifier (RFC 8707) and as the basis for the protected-resource
        metadata URL.
        """
        return AnyHttpUrl(f"{str(self.public_base_url).rstrip('/')}/mcp")

    @property
    def mcp_resource_metadata_url(self) -> AnyHttpUrl:
        """RFC 9728: the metadata path is /.well-known/oauth-protected-resource
        followed by the resource's path (here, "/mcp"). The SDK's route builder
        follows the same convention, so this URL is what gets advertised in
        `WWW-Authenticate` on 401 responses from /mcp.
        """
        return AnyHttpUrl(
            f"{str(self.public_base_url).rstrip('/')}"
            "/.well-known/oauth-protected-resource/mcp"
        )
