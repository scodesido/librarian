# Librarian

## Docker env vars
```
LIBRARIAN__GOOGLE_OAUTH__CLIENT_ID=...
LIBRARIAN__GOOGLE_OAUTH__CLIENT_SECRET=...
LIBRARIAN__BLOB_EXTRACTOR__ANTHROPIC_API_KEY=...
LIBRARIAN__NODE_EXTRACTOR__ANTHROPIC_API_KEY=...
LIBRARIAN__QUERY__ANTHROPIC_API_KEY=...
```

## Remote MCP via `ssh -R` + nginx

The FastAPI app exposes a Streamable-HTTP MCP endpoint at `/mcp`
(see `docs/11.mcp.md`). To make a local instance reachable by
claude.ai, we tunnel the local port to a port bound to `localhost`
on a remote machine that already terminates TLS, then reverse-proxy
to it from nginx inside a Docker container.

The endpoint is currently unauthenticated — keep it bound to
`localhost` on the remote, **never** to a public interface, and let
nginx be the only thing that can reach it.

### 1. Open the tunnel from the local machine

For a typical setup with a remote running an nginx reverse proxy container,
you first want to know what the gateway IP of the remote host on the nginx container:
```bash
ssh -t '<remote-ssh-hostname>' "sudo docker exec -t nginx-https getent hosts host.docker.internal"
```

Then, assuming nginx redirects to port 8642, use `ssh` to bind the local `8000` to the `(localhost:)8000` of the remote,
plus `socat` to redirect traffic from the `<host-gateway-IP>:8642` to the `8000` port on the remote.
This is required as the SSH tunnel will normally only bind to the localhost interface.
```bash
ssh -t -R 127.0.0.1:8000:127.0.0.1:8000 '<remote-ssh-hostname>' "socat -d TCP-LISTEN:8642,bind=<host-gateway-IP>,fork,reuseaddr TCP:127.0.0.1:8000"
```


### 2. nginx reverse-proxy config (inside the remote Docker container)

The remote already runs an nginx container terminating TLS for
`<your-host>`. Add the MCP site config below; replace `<your-host>`
with the hostname claude.ai will connect to, and `8001` with the
remote port chosen above.

```nginx
server {
    listen 443 ssl http2;
    server_name <your-host>;

    ssl_certificate     /etc/letsencrypt/live/<your-host>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<your-host>/privkey.pem;

    # MCP Streamable-HTTP endpoint. Single path, no sub-routing.
    # POST  = JSON-RPC request (may return a streamed SSE response).
    # GET   = server -> client notification stream.
    # DELETE = session terminate (unused in stateless mode).
    location = /mcp-tunnel/ {
        proxy_pass         http://host.docker.internal:8642/;

        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Streamable-HTTP keeps the response open and pushes events;
        # disable any nginx-side buffering or it'll batch them up.
        proxy_buffering    off;
        proxy_cache        off;
        chunked_transfer_encoding on;

        # Long read timeout: a retrieval can take tens of seconds while
        # the agent descends the tree. Keep it high enough that nginx
        # doesn't kill an in-flight call.
        proxy_read_timeout   600s;
        proxy_send_timeout   600s;
        proxy_connect_timeout 30s;
    }

    # Optional: deny everything else if this host is dedicated to MCP.
    location / {
        return 404;
    }
}
```

`host.docker.internal` resolves to the Docker host from inside the
container; if your container is run with `--network host`, use
`127.0.0.1:8001` instead. If `host.docker.internal` doesn't resolve
in your distro, add
`--add-host=host.docker.internal:host-gateway` to the container's
run flags.

Reload nginx (`nginx -s reload` inside the container) after dropping
the file into `/etc/nginx/conf.d/`.

### 3. Connect from claude.ai

Add `<your-host>/mcp-tunnel/` as a remote MCP server in claude.ai's
settings. Since the endpoint is unauthenticated, treat the hostname
itself as the secret — do not share the URL.
