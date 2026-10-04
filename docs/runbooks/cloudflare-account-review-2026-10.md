# Cloudflare Account Review — 2026-10-04

Review of `BTH Account` (10 zones) with focus on `68cc.io`, done via
the Cloudflare API MCP and cross-checked against this repo. The findings below
are as found; see **Applied 2026-10-04** at the end for what was changed.

## Snapshot

| Area | State |
|---|---|
| Zone `68cc.io` | Free plan, active, DNSSEC active, Universal SSL (Google CA, LE backup) |
| Tunnel `home` | Healthy, 2 connectors × 4 conns (bos/ewr), `cloudflared 2026.9.3`, remote config, ingress `68cc.io` + `*.68cc.io` → `traefik-external:443` with TLS verify ON, catch-all 404 |
| Custom rules | 5/5 used |
| Rate limiting | 1/1 used |
| Access (Zero Trust) | 7 self-hosted apps behind Google IdP + `josh-only` policy |
| Account | 1 member (Super Admin), 2FA enforced at account level |
| Traffic (7d) | ~3.4k–30k req/day; 5–30% blocked at edge as threats; edge cache hit ≈ 0% (expected for auth-gated dynamic apps) |

## Findings

### High

**H1. `pg.68cc.io` is published publicly through the tunnel, contrary to repo intent.**
Cloudflare has a proxied `pg.68cc.io` CNAME → tunnel (TXT owner `crd/databases/postgres-external`).
Public DoH resolves it to Cloudflare anycast; the edge returns 404 from Traefik.
`kubernetes/apps/databases/cloudnative-pg/cluster/dnsendpoint.yaml` says this record
must be LAN-only. Probable cause: `cloudflare-dns` has `sources: ["crd", ...]` with
`--force-default-targets`, so every `DNSEndpoint` (including the LAN-only
`postgres-internal`) gets rewritten to the tunnel CNAME. Postgres itself is not reachable
(the tunnel serves HTTP only, and `traefik-external` has no TCPRoute), but the record
advertises the database hostname and breaks the split-horizon design.
*Fix:* remove `crd` from `cloudflare-dns` `sources` (no other DNSEndpoint needs it), or add
`--label-filter` and only publish labeled CRDs. Then delete the stale CNAME and TXT records.

**H2. The Authentik rate-limit rule targets the wrong path, and one custom rule does nothing.**
- `rl-auth-endpoints` matches `/if/flow/`. That path only serves the flow SPA shell.
  Credential submissions go to `POST /api/v3/flows/executor/<slug>/`, which the rule never counts.
- `challenge-auth-brute-force` matches `/oauth2/start` and `/oauth2/sign_in`. Those are
  oauth2-proxy paths, and oauth2-proxy has been replaced by Authentik. The rule uses a slot and never fires.
*Fix:* point the rate limit at `http.host eq "auth.68cc.io" and starts_with(http.request.uri.path, "/api/v3/flows/executor/") and http.request.method eq "POST"`.
Use the freed custom-rule slot for H4/M1.

**H3. Some high-value hostnames have only one auth layer.**
CF Access covers apex, grafana, links, tools, paperless, and konflate. It does not cover
`holyclaude` (an agent with shell access and stored credentials), `omniroute` (an LLM gateway
that holds provider keys), or `tasks`. Those rely only on the Authentik forwardAuth
middleware. I verified that it does redirect to Authentik. Any Authentik bypass CVE would
reach them directly, though.
*Fix:* add Access apps for `holyclaude.68cc.io` (shorter session, e.g. 8h) and `tasks.68cc.io`.
For `omniroute`, add an Access app with a **service-token** policy for API clients (Home
Assistant, n8n), alongside `josh-only` for the UI.

### Medium

**M1. Runbook drift: the `flux-webhook-github-only` block rule is gone.**
The rule was replaced by an `allowed-webhooks` *skip* rule. Skip lets GitHub IPs through, but
nothing blocks non-GitHub IPs any more, so `flux-webhook.68cc.io` accepts POSTs from any
US/CA IP. Payloads are HMAC-verified, so the main risk is resource waste. The skip rule also
lacks GitHub's IPv6 hook ranges (`2a0a:a440::/29`, `2606:50c0::/32`, from `api.github.com/meta` today).
*Fix:* put the GitHub hook CIDRs (v4 and v6) in a Cloudflare **IP List**
(Free includes 1 list), reference `$github_hooks` in both the skip rule and a block rule, and
update `docs/runbooks/cloudflare-waf.md`.

**M2. Authentik admin UI is reachable from the internet.**
`auth.68cc.io` cannot sit behind Access because it *is* the IdP, so `/if/admin/` is exposed
to any US/CA IP. LAN clients resolve `auth.68cc.io` to the internal VIP through split horizon
and never pass through Cloudflare. That makes an edge block safe.
*Fix:* add a custom rule that blocks `http.host eq "auth.68cc.io" and starts_with(http.request.uri.path, "/if/admin")`.

**M3. Home WAN IP is published in public DNS.**
`home.68cc.io` A `100.0.186.56` is DNS-only, as is `home.bth.wtf` (which also has a stale
`104.18.0.0` record). Publishing the WAN IP gives up one of the tunnel's main benefits:
hiding the origin from scanners and direct DDoS. If it is only a DDNS anchor for VPN, move it
to an unguessable name or use the UniFi/WireGuard endpoint by IP. If it is unused, delete it.

**M4. Zone settings that break apps or are footguns.**
| Setting | Now | Recommend | Why |
|---|---|---|---|
| `ssl` | Flexible | **Full (strict)** | No effect on tunnel hostnames today. Any future proxied A/CNAME to a non-tunnel origin would silently go plaintext. Cloudflare docs say not to use Flexible with tunnels. |
| `rocket_loader` | on | **off** | Rewrites `<script>` tags. Known to break SPAs (Grafana, Authentik, HA, n8n) and fights the CSP middleware. |
| `email_obfuscation` | on | **off** | Injects `/cdn-cgi/` JS into HTML. Not useful for private apps. |
| `browser_cache_ttl` | 31536000 (1y) | **0 (respect origin)** | Overrides shorter origin `Cache-Control` on cacheable assets, which leaves stale JS/CSS after app upgrades. |
| `0rtt` | on | off (optional) | Replayable early data. Low risk at this traffic volume, but nothing needs it. |

**M5. No email anti-spoofing on `68cc.io`.**
There are no MX, SPF, or DMARC records, so anyone can send mail as `@68cc.io`. The repo
shows no mail sent from this domain.
*Fix (parked-domain set):* `TXT 68cc.io "v=spf1 -all"`, `TXT _dmarc "v=DMARC1; p=reject; sp=reject; adkim=s; aspf=s; rua=mailto:josh@bth.wtf"`, `MX 0 .` (null MX).
The family `*simmonds.com` zones already use this pattern.

### Low / hygiene

- `block-ai-crawlers-on-app-paths` lists `ai.68cc.io`, which has no DNS record. It misses
  `holyclaude`, `omniroute`, `konflate`, `tasks`, and `sh`. Invert it to
  `cf.client.bot and not http.host in {"flux-webhook.68cc.io" "68cc.io"}` so new apps are covered automatically.
- Stale objects: `_acme-challenge.{dsm,photos,rustfs}` TXT records, the `openclaw.68cc.io`
  Access app (no DNS record), a duplicate unused `josh-only` Access policy, and `bth.wtf`
  proxied CNAMEs (`cd`, `grafana`, `links`, `sh`, `tools`, `flux-webhook`, `external`)
  pointing at the home tunnel, which only routes `*.68cc.io`. Those names hit the catch-all
  404 or time out.
- Access policy `josh-only` is email-only. Add a `require` for Google MFA (`auth_method: mfa`)
  so a stolen Google session cookie isn't sufficient on its own.
- Other zones: `joshsimmonds.com`, `rjsimmonds.com`, `roysimmonds.com`, `zachsimmonds.com`, and
  `zjsimmonds.com` use Flexible SSL with min TLS 1.0. Some also have Always-Use-HTTPS off.
  `200pope.us` is empty with DNSSEC disabled. `robinhoodpto.com` has DMARC `p=none`.
  `beholdthehurricane.com` has SSL **off** and SPF `~all`.
- API tokens could not be listed (the MCP token lacks `Account API Tokens:Read`). Audit them
  manually: the external-dns token should be `Zone:DNS:Edit` on `68cc.io` only, and the MCP
  token should have an expiry.

### What's already good

The tunnel runs with origin TLS verification and `originServerName`, plus a catch-all 404.
DNSSEC is on. Min TLS is 1.3, with HSTS preload, PQ key exchange, and ECH. Account 2FA is
enforced. AI-bot blocking is on and Bot Fight Mode is correctly off. Geo-allowlisting happens
at the edge. Most apps are double-gated (Access + Authentik).

## Performance

Little to gain. Traffic is low-volume, authenticated, and dynamic. 304s dominate, so browser
revalidation is working. Edge caching of auth-gated apps is a risk, not a win. HTTP/3, Brotli,
and Early Hints are already on. Turning off Rocket Loader (M4) is the only change likely to
make a visible difference. Argo Smart Routing is not worth paying for, because the tunnel
already terminates at BOS/EWR colos close to home.

## If we buy Pro for `68cc.io` (~$20/mo annual, $25/mo monthly)

Pro is a "nice to have", not a fix. Every High/Medium item above can be done on Free.
Pro's real value here is Managed Rules (virtual patching for Authentik, Grafana, and others)
and more room for custom rules.

| Pro feature | What I'd configure |
|---|---|
| **Cloudflare Managed Ruleset** | Deploy on the zone with defaults. Skip it for `flux-webhook` (signed JSON) and for `omniroute` `/v1/*` (LLM prompts trip SQLi/XSS signatures). Run in Log for ~1 week, then switch to default actions. |
| **OWASP Core Ruleset** | Paranoia level 1, threshold Medium, action **Log** only. Raise to Managed Challenge on `auth.68cc.io` after tuning. PL2+ is too noisy for Grafana and n8n. |
| **Custom rules 5 → 20** | Split the merged rules back out: GitHub-hook skip and block (IP list), Authentik admin block, geo-allow, exploit paths (expanded: `/cgi-bin/`, `/vendor/phpunit`, `/.DS_Store`, `/server-status`, `/xmlrpc.php`), AI-crawler block (inverted host list), HTTP-method allowlist (block `TRACE`/`CONNECT`), a block on empty or obvious scanner UAs (`zgrab`, `masscan`, `nuclei`), and per-app Skip rules for API clients. |
| **Rate limiting 1 → 2** (Managed Challenge action, longer windows/timeouts) | RL1: Authentik executor POSTs, 10/min per IP → block 10 min. RL2: catch-all `not http.host in {"flux-webhook.68cc.io"}`, 600/min per IP → managed challenge 5 min, as a backstop for the in-cluster Traefik limiter. |
| **Super Bot Fight Mode** | Turn it on carefully. Cloudflare docs say **Definitely Automated must stay Allow** on tunnel zones (this is the same `websocket: bad handshake` failure we hit with BFM). That leaves Verified Bots = Block (we serve no SEO content) and static resource protection on. The value is modest, so expect most bot protection to keep coming from custom rules and Access. |
| **Security Events / Analytics** | Get per-rule hit visibility, which the API currently refuses on Free (`firewallEventsAdaptiveGroups` access denied). Use it to tune the managed rules. |
| **Leave off** | Polish, Mirage, image resizing, and APO bring no benefit for private apps. |

Rollout order: (1) do all Free fixes, (2) upgrade, (3) Managed + OWASP in Log for 7 days,
(4) tune and enforce, (5) SBFM with Definitely Automated=Allow while watching tunnel health,
(6) update `docs/runbooks/cloudflare-waf.md` and the `CLAUDE.md` Key Design Decisions line.
Revisit Business only if regex rules, WAF attack score, or "likely automated" bot actions become necessary.

## Applied 2026-10-04 (Pro activated on `68cc.io`)

Deployed state now lives in `docs/runbooks/cloudflare-waf.md`.

| Finding | Action taken |
|---|---|
| H1 `pg.68cc.io` public | Removed the `crd` source from `cloudflare-dns` (this PR). On merge, sync policy deletes the CNAME and TXT. |
| H2 Authentik rate limit / dead rule | `rl-authentik-flow-executor` targets executor POSTs, 10/min → block 10 min. Removed the oauth2 rule. |
| H3 single-layer apps | Added Access apps for `holyclaude` (8h), `omniroute`, and `tasks`. A bypass app keeps `tasks` `/api/v1`, `/api/v2`, `/dav`, and `/.well-known/caldav` reachable for token clients. |
| M1 flux-webhook | Added the `github_hooks` IP list (v4 + v6), a skip rule, and a block for everything else. The old skip matched `/webhook`, but Flux serves `/hook/`, so the skip never fired. |
| M2 Authentik admin | `/if/admin*` is blocked at the edge. |
| M3 WAN IP in DNS | **Not changed.** `home.68cc.io` / `home.bth.wtf` → `100.0.186.56` may be a VPN DDNS anchor. Needs a decision. The bogus `home.bth.wtf` A `104.18.0.0` was deleted. |
| M4 zone settings | ssl strict, rocket_loader off, email_obfuscation off, browser_cache_ttl 0, 0rtt off. |
| M5 email | Added `v=spf1 -all`, DMARC `p=reject` (rua `josh@bth.wtf`, authorized via `68cc.io._report._dmarc.bth.wtf`), and null MX. |
| Hygiene | Deleted `_acme-challenge.{dsm,photos,rustfs}`, the `openclaw` Access app, the duplicate `josh-only` policy, and the `bth.wtf` CNAMEs `cd`, `external`, `flux-webhook`, `grafana`, `links`, `sh`, and `tools`. The AI-crawler rule is inverted to cover all hosts. |
| Other zones | All 9: ssl strict, Always Use HTTPS on, min TLS 1.2. None have real web origins. Only Google `_domainconnect` CNAMEs are proxied. |
| Pro | Cloudflare Managed Ruleset, OWASP PL1/threshold 60/managed challenge (scoped off agent and API paths), SBFM verified bots = block (definitely automated = allow), 8 custom rules, 2 rate limits, leaked-credential detection on. |

Deliberately not changed: the Access MFA `require` (with the Google IdP, an
`auth_method: mfa` requirement can lock you out unless Google returns `amr`. Test it on
one app first), `robinhoodpto.com` DMARC `p=none` and `beholdthehurricane.com`
SPF `~all` (live mail domains, so ramp them deliberately), and `200pope.us` DNSSEC (needs a DS record at
the registrar).
