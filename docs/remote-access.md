# Remote access

By default, a leika server binds to `0.0.0.0:8080`, so it is reachable through
the machine's network interfaces even though its printed convenience URL uses
`localhost`. Use `Server(host="127.0.0.1")` when it should be local only.

Wildcard binds accept localhost spellings and IP-literal URLs by default. A
DNS, mDNS, or Tailscale name must be explicitly allowed:

```python
server = leika.Server(
    host="0.0.0.0",
    allowed_hosts=["camera.local", "demo.tailnet-name.ts.net"],
)
```

Allowlist entries are hostnames or IP literals only -- no schemes, ports,
paths, or wildcards. An explicit DNS bind automatically accepts its own name.
This is a DNS-rebinding defense: a hostile page must not be able to point a
name it controls at a Leika server and use a browser as a local-network proxy.
The browser `Origin`, when present, must also match the effective scheme,
hostname, and port.

Embedding is denied by default with `Content-Security-Policy: frame-ancestors
'none'`. Opt in for a trusted parent page with
`Server(allow_embedding=True)`. Notebook `show()` also requires that opt-in.
This permits framing; it does not bypass Host, Origin, or password checks.

For a server on another machine, the usual path is port forwarding
(`ssh -L 8080:localhost:8080 ...`). When forwarding is unavailable, a password
gate, share tunnel, or mesh VPN can provide controlled remote access.

## Password protection

```python
server = leika.Server(password="hunter2")
```

With a password set, everything the server speaks -- the web client and the
websocket underneath it -- refuses unauthenticated requests. Browsers get a
login page; a correct password earns a session cookie that lasts until the
server restarts.

Scripts can skip the cookie and send the password directly, URL-encoded, in a
header:

```bash
curl -H "x-leika-password: hunter2" http://localhost:8080/
```

The password check runs before workspace/client content is served or a
websocket is accepted. An anonymous URL gets only the minimal login surface.

## Share tunnels

```python
server = leika.Server(host="127.0.0.1", share=True)
```

`share=True` opens a [Cloudflare quick
tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
and prints a public URL:

```
Leika listening at http://127.0.0.1:8080
Leika share URL: https://drop-formal-lake-born.trycloudflare.com
Leika password (auto-generated): mV4nP-xq2Lw9
```

Open that URL from any machine and log in with the password. No port
forwarding, no accounts: the tunnel is an *outbound* connection from the
server to Cloudflare's edge, so it works from behind NATs, firewalls, and
VPNs. The edge terminates TLS, which also upgrades the client's websocket to
`wss://`.

Sharing requires the `cloudflared` binary on the `PATH`:

```bash
brew install cloudflared  # macOS; other platforms:
# https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
```

Because the URL is public, sharing always requires a password: pass your own
with `password=...`, or leave it unset and a random one is generated and
printed as above. The URL is random per run and dies with the server (or with
`server.stop()`); the current one is available as `server.share_url`. It can
take a few seconds after printing before Cloudflare's edge starts serving it
-- until then requests answer with error 530 -- so give a fresh URL a moment
before reloading.

Quick tunnels are Cloudflare's free, anonymous tier and come with no uptime
promise. Leika's built-in proxy trust is deliberately limited to the exact
quick-tunnel hostname created by `share=True`. An independently launched or
named Cloudflare tunnel is therefore not a drop-in replacement: its forwarded
headers are rejected unless Leika gains an explicit trusted-proxy
configuration for that deployment.

## Mesh VPNs

When every viewing machine is one you control, a mesh VPN such as
[Tailscale](https://tailscale.com) beats a tunnel: traffic stays end-to-end
encrypted between your own devices, nothing is published to the internet,
and the network does the reaching. Tell Leika which tailnet name the browser
will use:

```python
server = leika.Server(
    host="0.0.0.0",
    allowed_hosts=["machine-name.tailnet-name.ts.net"],
)
```

Install Tailscale on both machines and log in to the same account, then open
that allowed URL from anywhere on the tailnet. On a machine
where you have no root (a cluster node, say), the static binaries run
entirely from `$HOME`:

```bash
mkdir -p ~/tailscale ~/.tailscale && cd ~/tailscale
TAILSCALE_VERSION=1.102.2  # Recheck https://pkgs.tailscale.com/stable/
TAILSCALE_SHA256=ad2cde12f8de95f7b93a1e0401e652291c603d42b9d60a33fb1741eb38ab04d8
TAILSCALE_ARCHIVE="tailscale_${TAILSCALE_VERSION}_amd64.tgz"
curl -fsSLo "$TAILSCALE_ARCHIVE" \
  "https://pkgs.tailscale.com/stable/$TAILSCALE_ARCHIVE"
printf '%s  %s\n' "$TAILSCALE_SHA256" "$TAILSCALE_ARCHIVE" | sha256sum -c -
tar xzf "$TAILSCALE_ARCHIVE" --strip-components=1
nohup ./tailscaled --tun=userspace-networking \
  --statedir="$HOME/.tailscale" --socket="$HOME/.tailscale/tailscaled.sock" \
  > "$HOME/.tailscale/tailscaled.log" 2>&1 &
./tailscale --socket="$HOME/.tailscale/tailscaled.sock" up  # prints a login URL
```

In this userspace mode, inbound tailnet connections are proxied to localhost.
Bind to `127.0.0.1`, then allow the hostname that appears in the browser:

```python
server = leika.Server(host="127.0.0.1", allowed_hosts=["machine-name.tailnet-name.ts.net"])
```

No `share=True` is involved. A password is still worth setting: it separates
the dashboard from everything else that can reach the tailnet.

One caution: on employer-managed machines, a personal VPN may be a policy
conversation before it is a technical one. Have it first.

## Security model

What the gate guarantees, none of it depending on the code being secret:

- When a password is configured, every request authenticates before
  workspace/client content or a websocket is served. The only pre-auth
  surface is the login page itself and the two fonts it renders in.
- Password and session-token comparisons are constant-time, and the session
  token is 256 random bits minted per process -- a restart signs everyone
  out.
- With a password configured, wrong guesses are throttled globally (ten per
  minute, across every door a password fits in), so an online brute-force
  cannot outrun even a modest password. Established sessions ride through a
  lockout untouched.
- Every HTTP and websocket request passes Host validation, and browser
  requests with an `Origin` must match the normalized effective origin. This
  is what blocks DNS rebinding and cross-site websocket hijacking; the
  `HttpOnly`, `SameSite=Lax` session cookie is additional defense and is
  marked `Secure` over TLS.
- Responses prevent MIME sniffing and suppress referrer leakage. Framing is
  denied unless `allow_embedding=True` was explicit.

What the gate cannot promise:

- **A Leika server is trusted application code, not untrusted content.** The
  protocol can ask the client to run JavaScript and render HTML supplied by
  the server. This is intentional -- it is how Python-side extensions can
  load browser renderers and provide rich controls -- but it gives the server
  the same authority as the page itself. Only open servers whose operator and
  Python program you trust; a password controls who may reach a server, not
  what an authenticated server may do in the browser.
- **Cloudflare sees the traffic.** TLS terminates at their edge and is
  re-established into the tunnel, so the dashboard's bytes exist in
  Cloudflare's memory in the clear -- true of any proxied tunnel service.
  If that is unacceptable for the data on the dashboard, don't tunnel it:
  a mesh VPN such as Tailscale keeps traffic end-to-end encrypted between
  your own machines and never publishes a URL at all.
- The default `host="0.0.0.0"` serves plain HTTP on the local network,
  where the password would travel unencrypted -- which is why `share=True`
  refuses to start on anything but a loopback host: with the tunnel open,
  the only routes in are localhost and the tunnel itself.
- The printed URL and password land in terminal scrollback and logs; treat
  them like the secrets they are.
