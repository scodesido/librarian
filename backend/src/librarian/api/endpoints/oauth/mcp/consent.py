"""User-facing bridge endpoints for the MCP OAuth flow.

The MCP SDK's `/authorize` handler calls `provider.authorize()`, which
stashes a pending grant and returns a URL pointing at `/oauth/mcp/continue`.
That URL is what the SDK 302s the user to. These endpoints take over from
there:

  /oauth/mcp/continue   - dispatch: send to Google login if no session,
                          otherwise jump to the consent page.
  /oauth/mcp/consent    - GET renders the consent UI. POST applies the
                          decision: on allow, flip the grant to `granted`
                          and 302 back to the MCP client's redirect_uri
                          with `?code=...&state=...`; on deny, 302 back
                          with `?error=access_denied&state=...`.

PKCE and redirect-URI matching happen at the SDK's /token endpoint, not
here. Our only job is to attach a verified user to the grant.
"""

import html
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Cookie, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from mcp.server.auth.provider import construct_redirect_uri

from librarian.api.db import DbConnection
from librarian.api.settings import settings
from librarian.db.tables.auth_sessions import AuthSessions
from librarian.db.tables.oauth_authorization_grants import OAuthAuthorizationGrants
from librarian.db.tables.oauth_clients import OAuthClients

router = APIRouter(prefix="/oauth/mcp")


# Inline CSS so the consent page has no FE dependency. System sans-serif
# stack, restrained palette, generous spacing — meant to read as "this is
# a security prompt, not an app screen". The two buttons share a row so
# Allow/Deny feel symmetric (no implicit primary action that the user
# might click through reflexively).
CONSENT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Authorize {client_name} — Librarian</title>
<style>
  :root {{
    color-scheme: light dark;
    --fg: #1a1a1a;
    --fg-muted: #5a5a5a;
    --bg: #fafafa;
    --card-bg: #ffffff;
    --border: #e5e5e5;
    --accent: #2563eb;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --fg: #f5f5f5;
      --fg-muted: #a3a3a3;
      --bg: #111111;
      --card-bg: #1a1a1a;
      --border: #2a2a2a;
      --accent: #60a5fa;
    }}
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0;
    padding: 0;
    height: 100%;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: var(--bg);
    color: var(--fg);
    font-size: 16px;
    line-height: 1.5;
  }}
  main {{
    min-height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }}
  .card {{
    width: 100%;
    max-width: 440px;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 32px;
  }}
  h1 {{
    font-size: 20px;
    font-weight: 600;
    margin: 0 0 16px;
    letter-spacing: -0.01em;
  }}
  p {{ margin: 0 0 16px; color: var(--fg-muted); }}
  p strong {{ color: var(--fg); font-weight: 600; }}
  .scope {{
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
    margin: 20px 0;
    font-size: 14px;
  }}
  .scope-title {{
    font-weight: 600;
    color: var(--fg);
    margin-bottom: 4px;
  }}
  form {{
    display: flex;
    gap: 12px;
    margin-top: 24px;
  }}
  button {{
    flex: 1;
    padding: 10px 16px;
    border-radius: 8px;
    font-family: inherit;
    font-size: 15px;
    font-weight: 500;
    cursor: pointer;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--fg);
    transition: background 0.15s ease;
  }}
  button:hover {{ background: rgba(127, 127, 127, 0.08); }}
  button.primary {{
    background: var(--accent);
    border-color: var(--accent);
    color: #ffffff;
  }}
  button.primary:hover {{ filter: brightness(1.05); }}
</style>
</head>
<body>
<main>
  <div class="card">
    <h1>Authorize {client_name}</h1>
    <p><strong>{client_name}</strong> is requesting access to your Librarian library on your behalf.</p>
    <div class="scope">
      <div class="scope-title">It will be able to</div>
      <div>Search and read fragments from your indexed documents.</div>
    </div>
    <p>You are signed in as user <strong>#{user_id}</strong>. Approving will give {client_name} a long-lived token that you can revoke at any time.</p>
    <form method="post" action="/oauth/mcp/consent">
      <input type="hidden" name="nonce" value="{nonce}">
      <button type="submit" name="decision" value="deny">Deny</button>
      <button type="submit" name="decision" value="allow" class="primary">Allow</button>
    </form>
  </div>
</main>
</body>
</html>
"""


SessionCookie = Annotated[
    str | None, Cookie(alias=settings.cookies.session_cookie_name)
]


def login_redirect(nonce: str) -> RedirectResponse:
    """Bounce the user through the existing Google sign-in flow, asking
    it to come back to /continue with the same nonce once a session
    cookie has been minted.
    """
    next_path = f"/oauth/mcp/continue?{urlencode({'nonce': nonce})}"
    return RedirectResponse(
        f"/oauth/google/login?next={quote(next_path, safe='')}",
        status_code=303,
    )


@router.get("/continue")
async def cont(
    nonce: str,
    conn: DbConnection,
    session_id: SessionCookie = None,
) -> RedirectResponse:
    # The pending-grant lookup serves two purposes: it tells us the nonce
    # is valid (so we don't bounce the user through a useless Google
    # round trip), and it gives us the client_id we need on the consent
    # page. Expired/unknown nonces hard-fail rather than redirect — the
    # MCP client should kick off a fresh /authorize.
    grant = await OAuthAuthorizationGrants(conn).get_pending(nonce)
    if grant is None:
        raise HTTPException(
            status_code=400, detail="Unknown or expired authorization request"
        )
    user_id: int | None = None
    if session_id:
        user_id = await AuthSessions(conn).resolve(session_id)
    if user_id is None:
        return login_redirect(nonce)
    return RedirectResponse(
        f"/oauth/mcp/consent?{urlencode({'nonce': nonce})}", status_code=303
    )


@router.get("/consent", response_model=None)
async def consent_page(
    nonce: str,
    conn: DbConnection,
    session_id: SessionCookie = None,
) -> HTMLResponse | RedirectResponse:
    grant = await OAuthAuthorizationGrants(conn).get_pending(nonce)
    if grant is None:
        raise HTTPException(
            status_code=400, detail="Unknown or expired authorization request"
        )
    user_id: int | None = None
    if session_id:
        user_id = await AuthSessions(conn).resolve(session_id)
    if user_id is None:
        # Defence in depth — `/continue` should have caught this already,
        # but if someone hit /consent directly without a session, send
        # them through login.
        return login_redirect(nonce)
    client = await OAuthClients(conn).get(grant.client_id)
    raw_client_name = client.client_name if client is not None else "an MCP client"
    # `client_name` is attacker-controlled (anyone can /register with
    # arbitrary content), so escape it for HTML before interpolating. The
    # nonce comes from `secrets.token_urlsafe` and is URL-safe, but escape
    # it too for consistency — defence in depth against a future change
    # that switches to a less-restricted code alphabet.
    body = CONSENT_HTML.format(
        client_name=html.escape(raw_client_name),
        nonce=html.escape(nonce),
        user_id=user_id,
    )
    return HTMLResponse(content=body)


@router.post("/consent")
async def consent_decision(
    conn: DbConnection,
    nonce: Annotated[str, Form()],
    decision: Annotated[str, Form()],
    session_id: SessionCookie = None,
) -> RedirectResponse:
    grant = await OAuthAuthorizationGrants(conn).get_pending(nonce)
    if grant is None:
        raise HTTPException(
            status_code=400, detail="Unknown or expired authorization request"
        )
    user_id: int | None = None
    if session_id:
        user_id = await AuthSessions(conn).resolve(session_id)
    if user_id is None:
        # A consent POST from an unauthenticated browser should not be
        # possible under normal use; reject hard rather than re-running
        # the login bounce because the form is one-shot.
        raise HTTPException(status_code=401, detail="Not signed in")

    if decision == "deny":
        target = construct_redirect_uri(
            grant.redirect_uri,
            error="access_denied",
            error_description="The user denied the authorization request.",
            state=grant.client_state,
        )
        return RedirectResponse(target, status_code=303)

    if decision != "allow":
        raise HTTPException(status_code=400, detail="Invalid decision")

    if not await OAuthAuthorizationGrants(conn).grant(nonce, user_id):
        # Lost the race or the grant expired between the GET and the POST.
        raise HTTPException(
            status_code=400, detail="Unknown or expired authorization request"
        )
    target = construct_redirect_uri(
        grant.redirect_uri,
        code=nonce,
        state=grant.client_state,
    )
    return RedirectResponse(target, status_code=303)
