# Cloudflare WAF + Bot Management Runbook

Source-of-truth documentation for Cloudflare-side security controls on the
`68cc.io` zone (Free plan). The rules themselves live in the Cloudflare
dashboard — this doc is the reviewable, diff-able record of what **should**
exist, why, and how to verify.

## Scope

- **Zone**: `68cc.io` (id `eb20e71f8f6552f423760f6d9ba6e477`)
- **Account**: `BTH Account` (id `8ba89444e86d240c9e8ab1cd0ad60c2c`)
- **Plan**: Free — caps enforced throughout:
  - 5 custom rules
  - 1 rate-limiting rule
  - Block duration: 10s minimum
  - Rate-limit counting characteristics: `ip.src` + `cf.colo.id` only (per-colo, not global)

Related: `docs/runbooks/auth0-rotation.md` (superseded by the oauth2-proxy
migration — flagged stale), `kubernetes/apps/network/cloudflared/`,
`kubernetes/apps/network/traefik-external/`.

## Design intent

Traffic flow for `*.68cc.io` public hostnames:

```
client -> Cloudflare edge (Free plan WAF/rate-limit fires here)
       -> cloudflared tunnel (home tunnel, 2 replicas in network ns)
       -> traefik-external (gateway 192.168.35.15)
       -> oauth2-proxy forwardAuth
       -> backend
```

The rules below protect the edge step. Traefik's in-cluster middleware
(crowdsec-bouncer, rate-limit, bot-wrangler) is a second layer; the
Cloudflare rules are NOT redundant because they block before tunnel
ingress consumes bandwidth and before any pod spins up.

## Bot Management settings

| Setting | Value | Why |
|---|---|---|
| `fight_mode` (Bot Fight Mode) | **OFF** | BFM challenges `Definitely Automated`. Cloudflare-to-cloudflared connections fall into that bucket; enabling causes `websocket: bad handshake` errors and breaks the tunnel. Free plan has no per-rule override. Keep off. |
| `ai_bots_protection` | **block** | Blocks GPTBot, ClaudeBot, PerplexityBot, CCBot, Bytespider, etc. at edge. Free, no configuration cost. Defense-in-depth alongside Traefik's `bot-wrangler` plugin (robots.txt rewrite). |
| `is_robots_txt_managed` | true | Cloudflare injects anti-AI directives into robots.txt. |
| `content_bots_protection` / `crawler_protection` / `enable_js` | disabled | Pro+ features. Not applicable. |

## Custom rules (5/5)

Order of evaluation is top-to-bottom as listed in the dashboard. The
first `block` / `managed_challenge` wins.

### 1. `geo-allowlist-us-ca`

**Intent**: Drop traffic from countries other than US and Canada before
it enters the cluster. Replaced the Traefik `geoblock` plugin Middleware
in Phase 4.

**Expression**:
```
(not ip.src.country in {"US" "CA"})
```

**Action**: Block

**When to edit**:
- Traveling → add the country you're in, OR add a `ip.src eq <your-IP>`
  skip rule ahead of it
- Need an allowlist for a specific backend country: add another rule with
  higher priority using `Skip` action (consumes a custom-rule slot)

**Known false positives**: Any legitimate user on a VPN egressing from a
country outside the allowlist.

### 2. `block-ai-crawlers-on-app-paths`

**Intent**: Block Cloudflare-identified bots (`cf.client.bot`) on
human-facing apps only. Excludes `flux-webhook.68cc.io` (GitHub webhook
machine traffic) and the apex (`68cc.io` / Homepage).

**Expression**:
```
(cf.client.bot) and (http.host in {
  "grafana.68cc.io" "auth.68cc.io" "links.68cc.io" "n8n.68cc.io"
  "ai.68cc.io" "paperless.68cc.io" "sh.68cc.io" "tools.68cc.io"
})
```

**Action**: Block

**Note**: `cf.client.bot` is coarse on Free plan (no verified-bot
distinction — that's a Super Bot Fight Mode / Pro feature). Catches
Googlebot et al. Accept the tradeoff since none of these services expect
search-engine traffic.

**When to edit**: Add hostnames to the `http.host` list as new public
services come online. Do NOT add `flux-webhook` — GitHub webhook UA
triggers `cf.client.bot`.

### 3. `challenge-auth-brute-force`

**Intent**: Throttle brute-force attempts on the oauth2-proxy sign-in
endpoint via Managed Challenge.

**Expression**:
```
(http.host eq "auth.68cc.io"
 and http.request.uri.path in {"/oauth2/start" "/oauth2/sign_in"}
 and http.request.method eq "POST")
```

**Action**: Managed Challenge

**Note**: Free plan allows Managed Challenge in custom rules (not rate
limiting). Real rate-limit enforcement lives in `rl-auth-endpoints` below.

### 4. `block-common-exploits`

**Intent**: Block automated vulnerability probes for paths none of the
apps serve. Pure drop-on-the-floor rule.

**Expression**:
```
(http.request.uri.path contains "/.env") or
(http.request.uri.path contains "/.git/") or
(http.request.uri.path contains "/wp-admin") or
(http.request.uri.path contains "/wp-login.php") or
(http.request.uri.path contains "/phpinfo") or
(http.request.uri.path contains "/.aws/") or
(http.request.uri.path contains "/actuator")
```

**Action**: Block

**When to edit**: Add new exploit paths as they surface in CrowdSec logs
or access logs (`task flux:logs name=traefik-external ns=network` piped
through a 4xx filter).

### 5. `flux-webhook-github-only`

**Intent**: `flux-webhook.68cc.io` has no auth; GitHub signature-
validates the payload, but anyone can POST and waste resource. Scope the
endpoint to GitHub Actions webhook source IPs.

**Expression**:
```
(http.host eq "flux-webhook.68cc.io")
 and (not ip.src in {140.82.112.0/20 143.55.64.0/20 192.30.252.0/22 185.199.108.0/22})
```

**Action**: Block

**IP maintenance**: GitHub publishes current webhook CIDRs at
<https://api.github.com/meta> under `.hooks[]`. These change rarely but
DO change. When a flux-webhook reconcile starts failing post-push,
re-run:

```bash
curl -s https://api.github.com/meta | jq -r '.hooks[]'
```

Compare against the rule. Update the CIDR set in the dashboard (or via
MCP — see "Verify" below).

## Rate limiting rules (1/1)

### `rl-auth-endpoints`

**Intent**: Hard cap burst traffic to the entire `auth.68cc.io` host.
Complements `challenge-auth-brute-force` above by blocking when even the
challenge doesn't deter the attacker.

**Expression**:
```
(http.host eq "auth.68cc.io")
```

**Rate**: 20 requests per 10 seconds, per IP per colo
(`ip.src`, `cf.colo.id`)

**Action**: Block for 10 seconds

**Free-plan constraints**:
- Only 1 rate-limit rule allowed total. Cannot add a second generic app
  rule without a plan upgrade. The attempted `rl-apps-per-ip` rule from
  the Phase 4.3 runbook was dropped for this reason. Traefik's in-cluster
  `rate-limit` Middleware (60 req/s per replica) is the backstop.
- 10-second window is minimum on Free.
- Block duration is 10 seconds minimum on Free.

**Plan upgrade decision**: Pro plan ($20/mo) unlocks 10 rate-limit rules
+ Super Bot Fight Mode + Managed Rules. Revisit quarterly.

## Verify

Run this via the Cloudflare MCP (`cloudflare-api` server, authenticated
with the API token scoped to `Zone:Rulesets:Edit`). Produces a diff
report against what should exist.

```javascript
async () => {
  const zoneId = "eb20e71f8f6552f423760f6d9ba6e477";
  const cr = await cloudflare.request({
    method: "GET",
    path: `/zones/${zoneId}/rulesets/phases/http_request_firewall_custom/entrypoint`,
  });
  const rl = await cloudflare.request({
    method: "GET",
    path: `/zones/${zoneId}/rulesets/phases/http_ratelimit/entrypoint`,
  });
  const bfm = await cloudflare.request({
    method: "GET",
    path: `/zones/${zoneId}/bot_management`,
  });
  return {
    custom_count: cr.result?.rules?.length,
    custom_names: (cr.result?.rules || []).map(r => r.description),
    rate_limit_count: rl.result?.rules?.length,
    rate_limit_names: (rl.result?.rules || []).map(r => r.description),
    bfm: {
      fight_mode: bfm.result?.fight_mode,
      ai_bots_protection: bfm.result?.ai_bots_protection,
    },
  };
}
```

**Expected output**:
```json
{
  "custom_count": 5,
  "custom_names": [
    "geo-allowlist-us-ca",
    "block-ai-crawlers-on-app-paths",
    "challenge-auth-brute-force",
    "block-common-exploits",
    "flux-webhook-github-only"
  ],
  "rate_limit_count": 1,
  "rate_limit_names": ["rl-auth-endpoints"],
  "bfm": { "fight_mode": false, "ai_bots_protection": "block" }
}
```

## Observe

Monitor rule effectiveness:

- Dashboard → Security → Events — per-rule hit counts, sampled request
  details. Filter by rule name.
- `curl -I https://grafana.68cc.io/` from a non-US/CA VPN — expected
  `HTTP/2 403` from Cloudflare with `cf-ray` header identifying the
  block.
- Rate-limit trip: burst 25 POSTs at `/oauth2/start` in under 10s —
  first ~20 pass through, remaining get 429 from edge.

## Change management

**Recommended flow**:

1. Edit this markdown first (propose change in a PR against `main`).
2. Apply the change in the Cloudflare dashboard OR via the MCP.
3. Re-run the Verify snippet. Confirm diff is empty.
4. Merge the markdown PR.

**What this runbook does NOT cover** (deferred or plan-gated):

- IaC management via Terraform (`cloudflare/cloudflare` provider) — PoC
  task when the ruleset needs to grow beyond 5 rules.
- Managed Rules / OWASP Core Ruleset (Pro+ only).
- Super Bot Fight Mode (Pro+ only).
- Turnstile integration on form endpoints.
- Email routing / DMARC / SPF policies.
- R2 / Workers / Page Rules.
