# Remote access

By default, a leika server binds to `0.0.0.0:8080`, so it is reachable through
the machine's network interfaces even though its printed convenience URL uses
`localhost`. Use `Server(host="127.0.0.1")` when it should be local only.

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

The password check runs before anything else, including the websocket
handshake, so a URL alone -- leaked, guessed, or scanned -- gets nothing.

## Share tunnels

```python
server = leika.Server(host="127.0.0.1", share=True)
```

`share=True` opens a [Cloudflare quick
tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)
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
promise. For a stable address, a named tunnel on a Cloudflare account maps
your own domain to the same `cloudflared` process -- configuration on their
side, no leika changes -- and leika's password gate keeps working behind it.

## Mesh VPNs

When every viewing machine is one you control, a mesh VPN such as
[Tailscale](https://tailscale.com) beats a tunnel: traffic stays end-to-end
encrypted between your own devices, nothing is published to the internet,
and leika needs no options at all -- the network does the reaching.

Install Tailscale on both machines and log in to the same account, then open
`http://<machine-name>:8080` from anywhere on the tailnet. On a machine
where you have no root (a cluster node, say), the static binaries run
entirely from `$HOME`:

```bash
mkdir -p ~/tailscale ~/.tailscale && cd ~/tailscale
curl -fsSL https://pkgs.tailscale.com/stable/tailscale_1.98.10_amd64.tgz \
  | tar xz --strip-components=1
nohup ./tailscaled --tun=userspace-networking \
  --statedir="$HOME/.tailscale" --socket="$HOME/.tailscale/tailscaled.sock" \
  > "$HOME/.tailscale/tailscaled.log" 2>&1 &
./tailscale --socket="$HOME/.tailscale/tailscaled.sock" up  # prints a login URL
```

In this userspace mode, inbound tailnet connections are proxied to
localhost, so `Server(host="127.0.0.1")` is exactly right -- no `share=True`
involved. A password is still worth setting: it is what separates the
dashboard from everything else that can reach the tailnet.

One caution: on employer-managed machines, a personal VPN may be a policy
conversation before it is a technical one. Have it first.

## Security model

What the gate guarantees, none of it depending on the code being secret:

- Every request authenticates before anything is served: static files, the
  websocket handshake, everything. The one pre-auth surface is the login
  page itself and the two fonts it renders in.
- Password and session-token comparisons are constant-time, and the session
  token is 256 random bits minted per process -- a restart signs everyone
  out.
- Wrong guesses are throttled globally (ten per minute, across every door a
  password fits in), so an online brute-force cannot outrun even a modest
  password. Established sessions ride through a lockout untouched.
- The session cookie is `HttpOnly` and `SameSite=Lax` (which also blocks
  cross-site websocket hijacking), and marked `Secure` when it traveled
  over TLS.

What the gate cannot promise:

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
