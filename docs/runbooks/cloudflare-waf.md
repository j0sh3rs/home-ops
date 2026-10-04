# Cloudflare WAF + Bot Management Runbook

Source-of-truth documentation for Cloudflare-side security controls on the
`68cc.io` zone (**Pro plan**, since 2026-10-04). The rules themselves live in
Cloudflare, not in this repo — this doc is the reviewable, diff-able record of
what **should** exist, why, and how to verify. Background and the review that
produced this layout: `docs/runbooks/cloudflare-account-review-2026-10.md`.

## Scope

- **Zone**: `68cc.io` (id `eb20e71f8f6552f423760f6d9ba6e477`)
- **Account**: `BTH Account` (id `8ba89444e86d240c9e8ab1cd0ad60c2c`)
- **Plan**: Pro — caps:
  - 20 custom rules (9 used)
  - 2 rate-limiting rules (2 used), periods/timeouts up to 1h,
    characteristics `ip.src` + `cf.colo.id` only (per-colo, not global)
  - Cloudflare Managed Ruleset + OWASP Core Ruleset
  - Super Bot Fight Mode (SBFM)
  - No `log` action for custom rules (Enterprise only); test rules by
    deploying narrow expressions instead
- Rollback copy of the pre-2026-10-04 Free-plan rules: git history of this
  file (`git log -p docs/runbooks/cloudflare-waf.md`).

## Design intent

```
client -> Cloudflare edge: custom rules -> rate limits -> managed WAF -> SBFM
       -> Cloudflare Access (Google IdP, josh-only) on app hostnames
       -> cloudflared tunnel (home, 2 replicas in network ns)
       -> traefik-external (gateway 192.168.35.15)
       -> crowdsec bouncer + Authentik forwardAuth
       -> backend
```

LAN clients resolve `*.68cc.io` to the internal VIPs via unifi-dns and never
touch Cloudflare, so edge blocks (e.g. Authentik admin) don't affect LAN use.

## Zone settings

| Setting | Value | Why |
|---|---|---|
| `ssl` | `strict` | Every proxied record is a tunnel CNAME today; strict means any future non-tunnel origin can't silently go plaintext. |
| `rocket_loader` | off | Rewrites `<script>` tags — breaks SPAs and fights the CSP middleware. |
| `email_obfuscation` | off | Injects `/cdn-cgi/` JS; useless for private apps. |
| `browser_cache_ttl` | 0 (respect origin) | A forced 1y TTL left stale JS/CSS after app upgrades. |
| `0rtt` | off | Replayable early data; nothing needs it. |
| `min_tls_version` / HSTS | 1.3 / preload+includeSubDomains | Unchanged. |

## Bot Management settings

| Setting | Value | Why |
|---|---|---|
| `fight_mode` (Bot Fight Mode) | **OFF** | Free-tier BFM challenges `Definitely Automated` with no override; that breaks cloudflared (`websocket: bad handshake`). Superseded by SBFM. |
| `sbfm_definitely_automated` | **allow** | Must stay allow on a tunnel zone — same failure as BFM. |
| `sbfm_verified_bots` | block | We serve no SEO content. GitHub hooks are exempted by `skip-github-webhooks` (skips the SBFM phase). |
| `sbfm_static_resource_protection` / `enable_js` | false | No value for auth-gated apps; JS detection adds a script to every page. |
| `ai_bots_protection` | block | GPTBot, ClaudeBot, etc. |
| Leaked credentials detection | enabled | Detection only (sets `cf.waf.credential_check.*` fields); no action wired yet. |

## IP Lists (account-level)

- `github_hooks` (id `3befc744d3fa46ab906708823cc24a4c`): `.hooks[]` from
  <https://api.github.com/meta>, v4 + v6. Refresh when GitHub changes ranges:

  ```bash
  curl -s https://api.github.com/meta | jq -r '.hooks[]'
  ```

## Custom rules (9/20)

Evaluated top to bottom; the first terminating action wins.

| # | Name | Action | Expression |
|---|---|---|---|
| 1 | `skip-github-webhooks` | skip rest of custom rules + rate limit + managed WAF + SBFM (logged) | `(ip.src in $github_hooks) and (http.host eq "flux-webhook.68cc.io") and starts_with(http.request.uri.path, "/hook/")` |
| 2 | `skip-cloudflare-healthcheck` | skip rest of custom rules + SBFM (logged) | `(http.host eq "auth.68cc.io") and (http.request.uri.path eq "/-/health/live/") and (http.request.method eq "GET") and starts_with(http.user_agent, "Mozilla/5.0 (compatible;Cloudflare-Healthchecks/")` |
| 3 | `block-flux-webhook-non-github` | block | `(http.host eq "flux-webhook.68cc.io")` — anything not skipped by #1 |
| 4 | `geo-allowlist-us-ca` | block | `(not ip.src.country in {"US" "CA"})` |
| 5 | `block-bad-methods` | block | `(http.request.method in {"TRACE" "TRACK" "CONNECT"})` |
| 6 | `block-scanner-user-agents` | block | empty UA, or UA contains `zgrab`, `masscan`, `nuclei`, `sqlmap`, `nikto`, `censysinspect` (lower-cased) |
| 7 | `block-exploit-paths` | block | lower-cased path contains `/.env`, `/.git/`, `/.aws/`, `/.ds_store`, `/wp-admin`, `/wp-login.php`, `/xmlrpc.php`, `/phpinfo`, `/vendor/phpunit`, `/cgi-bin/`, `/server-status`, `/actuator` |
| 8 | `block-authentik-admin-external` | block | `(http.host eq "auth.68cc.io") and starts_with(lower(http.request.uri.path), "/if/admin")` |
| 9 | `block-ai-crawlers` | block | `(cf.client.bot) and (http.host ne "68cc.io")` |

Notes:

- Flux's Receiver is served on `/hook/<token>` (see
  `kubernetes/apps/flux-system/flux-instance/app/httproute.yaml`). The
  pre-2026-10 skip rule matched `/webhook`, so it never fired for flux.
- n8n is on `traefik-internal-gateway` only; it is not referenced here. If
  n8n webhooks are ever published, add its host/path to rule #1 rather than
  a new skip rule.
- Rule #2: Cloudflare's Health Check prober is `cf.client.bot`, so rule #9
  (and SBFM `verified_bots=block`) 403'd it. The UA is spoofable, but the
  skip only covers one public GET that returns 200 anyway; rate limiting and
  the managed WAF still apply.
- Rule #8: Authentik admin is LAN-only. Remote admin = VPN to LAN.
- Rule #6: an API client that sends no `User-Agent` will be blocked. Every
  known client (HA, CalDAV, mobile apps, atuin, curl) sends one.
- Travel: add a country to rule #4, or a temporary `ip.src eq <ip>` skip
  rule above it.

## Rate limiting rules (2/2)

| Name | Expression | Rate | Action |
|---|---|---|---|
| `rl-authentik-flow-executor` | `(http.host eq "auth.68cc.io") and starts_with(http.request.uri.path, "/api/v3/flows/executor/") and (http.request.method eq "POST")` | 10 / 60s per IP per colo | block 600s |
| `rl-global-backstop` | `(http.host ne "flux-webhook.68cc.io")` | 1200 / 60s per IP per colo | managed challenge 300s |

Authentik credential submissions are `POST /api/v3/flows/executor/<slug>/`;
`/if/flow/` only serves the SPA shell. A normal login is 3–5 POSTs. Traefik's
in-cluster rate-limit Middleware remains the per-app layer.

## Managed rules (`http_request_firewall_managed`)

| Name | Ruleset | Scope | Config |
|---|---|---|---|
| `cloudflare-managed-ruleset` | Cloudflare Managed Ruleset (`efb7b8c9…`) | all hosts except `holyclaude`, `omniroute`, `flux-webhook` | default actions |
| `owasp-core-pl1-threshold60` | OWASP Core (`4814384a…`) | same exclusions, plus `sh.68cc.io` and paths starting `/api/`, `/dav`, `/.well-known/` | PL1 only (PL2–4 categories disabled); rule `949110` threshold 60 (least sensitive), action managed challenge |

Why the exclusions: `holyclaude` and `omniroute` carry shell commands and LLM
prompts in request bodies, which trip SQLi/RCE signatures; both are behind
Access + Authentik. API/CalDAV/atuin clients can't solve a challenge, so OWASP
(the false-positive-prone ruleset) stays off those paths while the signature
ruleset still covers them.

Tuning: Security → Events, filter by service "Managed rules". For a
false positive, add a rule-level override (`overrides.rules[{id, enabled:false}]`)
in the execute rule rather than widening the scope.

## Access (Zero Trust)

Self-hosted apps, Google IdP, policy `josh-only` (`e5b8b31d…`), binding cookie:
apex, `grafana`, `links`, `tools`, `paperless`, `konflate` (24h),
`omniroute` (24h), `tasks` (24h), `holyclaude` (8h).

`tasks.68cc.io — API/CalDAV bypass` uses policy `bypass-app-auth-apis`
(bypass, everyone) on `/api/v1`, `/api/v2`, `/dav`, `/.well-known/caldav`:
Vikunja's mobile, CalDAV, and MCP clients authenticate with Vikunja tokens
and can't do an Access redirect. Mirrors the forwardAuth exemptions in
`kubernetes/apps/services/vikunja/app/helmrelease.yaml` — keep the two in sync.

`auth.68cc.io` and `flux-webhook.68cc.io` intentionally have no Access app
(IdP itself; GitHub machine traffic).

## Verify

Run via the Cloudflare MCP (`cloudflare-api`):

```javascript
async () => {
  const z = "eb20e71f8f6552f423760f6d9ba6e477";
  const ep = async (p) => (await cloudflare.request({ method: "GET",
    path: `/zones/${z}/rulesets/phases/${p}/entrypoint` })).result.rules.map(r => r.description);
  const bot = (await cloudflare.request({ method: "GET", path: `/zones/${z}/bot_management` })).result;
  const s = (await cloudflare.request({ method: "GET", path: `/zones/${z}/settings` })).result;
  return {
    custom: await ep("http_request_firewall_custom"),
    ratelimit: await ep("http_ratelimit"),
    managed: await ep("http_request_firewall_managed"),
    sbfm: { automated: bot.sbfm_definitely_automated, verified: bot.sbfm_verified_bots, ai: bot.ai_bots_protection },
    settings: Object.fromEntries(s.filter(x => ["ssl","rocket_loader","email_obfuscation","browser_cache_ttl","0rtt"].includes(x.id)).map(x => [x.id, x.value])),
  };
}
```

**Expected**:

```json
{
  "custom": ["skip-github-webhooks","skip-cloudflare-healthcheck","block-flux-webhook-non-github","geo-allowlist-us-ca","block-bad-methods","block-scanner-user-agents","block-exploit-paths","block-authentik-admin-external","block-ai-crawlers"],
  "ratelimit": ["rl-authentik-flow-executor","rl-global-backstop"],
  "managed": ["cloudflare-managed-ruleset","owasp-core-pl1-threshold60"],
  "sbfm": { "automated": "allow", "verified": "block", "ai": "block" },
  "settings": { "ssl": "strict", "rocket_loader": "off", "email_obfuscation": "off", "browser_cache_ttl": 0, "0rtt": "off" }
}
```

Edge smoke test (from LAN, LAN DNS short-circuits, so pin the edge IP):

```bash
IP=$(curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=grafana.68cc.io&type=A' | jq -r '.Answer[-1].data')
t(){ curl -s -o /dev/null -A 'Mozilla/5.0 verify' --resolve "$1:443:$IP" -w "%{http_code} $1$2\n" "${@:3}" "https://$1$2"; }
t grafana.68cc.io /                 # 302 -> bth.cloudflareaccess.com
t tasks.68cc.io /api/v1/info        # 200 (Access bypass)
t auth.68cc.io /if/admin/           # 403
t flux-webhook.68cc.io /hook/x -X POST  # 403 (not a GitHub IP)
t links.68cc.io /.env               # 403
```

## Monitoring and notifications

**Cloudflare Notifications** (account-level). Every policy delivers to email
`cloudflare@beholdthehurricane.com` and to webhook destination
`discord-home-ops-alerts` (`77ef7521…`, native Discord type, the same channel
Alertmanager uses via `alertmanager-secret`). If that Discord webhook is
rotated, update the destination as well.

| Policy | Alert type | Scope |
|---|---|---|
| `home-ops: tunnel health (home)` | `tunnel_health_event` | tunnel `3ecf7dee…`, every status change (incl. recovery) |
| `home-ops: tunnel created/deleted` | `tunnel_update_event` | account |
| `home-ops: auth edge health check` | `health_check_status_notification` | health check below, Healthy + Unhealthy |
| `home-ops: HTTP DDoS attack` | `dos_attack_l7` | all zones |
| `home-ops: Universal SSL` | `universal_ssl_event_type` | all zones |

**Health Check** `auth-edge-to-authentik` (`f509144d…`, Pro): HTTPS GET
`auth.68cc.io/-/health/live/` expecting 200, 60s interval, ENAM + WNAM,
unhealthy after 3 consecutive failures. It is the only external synthetic
probe: in-cluster probes resolve `*.68cc.io` to LAN VIPs and never touch the
edge. A pass proves edge → tunnel → traefik-external → Authentik. Needs
custom rule #2.

**Metrics**: `kubernetes/apps/monitoring/cloudflare-exporter/` (lablabs
`cloudflare_exporter`) polls GraphQL Analytics for 68cc.io with a dedicated
read-only token and is scraped by vmagent. Grafana: *Network → Cloudflare
Edge (68cc.io)*: requests/status by host, firewall events by
rule/action/host/country, origin p95. Alerts: `CloudflareAnalyticsMissing`,
`CloudflareEdge5xxHigh` (both warning). Tunnel-connector alerts live with
cloudflared. Read the helmrelease header before writing queries: the series
are per-minute windows, not counters.

## Change management

1. Edit this markdown first (PR against `main`).
2. Apply via the dashboard or the MCP. Custom/ratelimit/managed rules are
   replaced as a whole entrypoint ruleset with `PUT .../phases/<phase>/entrypoint`
   — always send the full rule list.
3. Re-run Verify and the smoke test; check that the tunnel is still `healthy`.
4. Merge the PR.

**Not covered** (candidates for future work): Terraform-managed rules,
Turnstile on forms, sampled security events → VictoriaLogs, Access-level MFA.
