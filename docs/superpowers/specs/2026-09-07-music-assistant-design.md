# Music Assistant Deployment — Design

Date: 2026-09-07
Status: Approved, pending implementation
Related: `kubernetes/apps/services/home-assistant/` (hostNetwork discovery
pattern being reused), `kubernetes/apps/services/homebridge/`,
`kubernetes/components/repos/app-template/`

## Context

The user wants Music Assistant (`music-assistant.io`) deployed in the
homelab: a local music library (files to be loaded onto a new share later)
plus Tidal streaming, played out to a mix of Sonos, Chromecast, and AirPlay
speakers, with Home Assistant integration for dashboards/automations.

Music Assistant has no upstream Helm chart — it ships as a single container
image, `ghcr.io/music-assistant/server`. Upstream docs require
`network_mode: host` because player discovery (Sonos SSDP, Chromecast/AirPlay
mDNS) and the multicast zeroconf broadcast HA uses to auto-discover MA both
need to be on the same L2 network as the speakers, with no VLAN hop. This
repo already solved the identical problem for `home-assistant`
(`pod.hostNetwork: true` + `dnsPolicy: ClusterFirstWithHostNet`), so this
deployment reuses that pattern rather than inventing a new one (e.g. macvlan
CNI).

## Scope decisions (from brainstorming Q&A)

- **Library**: local files (new share, to be populated later) + Tidal
  streaming. No Spotify for now.
- **Players**: Sonos, Chromecast, and AirPlay (all three, no scoping down).
- **HA integration**: yes — install HA's native "Music Assistant"
  integration after deploy; expect auto-discovery since both pods share the
  host network. No changes to `home-assistant`'s own manifests required —
  this is a runtime config step in HA's UI, not GitOps state.
- **Exposure**: internal-only, matching `home-assistant`'s posture — LAN via
  `traefik-internal-gateway`, no public Cloudflare record.

## Architecture

- New app: `kubernetes/apps/services/music-assistant/` — `services`
  namespace (groups with `home-assistant`/`homebridge`; already opted into
  the `app-template` component).
- `bjw-s/app-template` HelmRelease wrapping the raw
  `ghcr.io/music-assistant/server` image (renovate-tracked tag), same shape
  as how `home-assistant` itself wraps `homeassistant/home-assistant`.
- `pod.hostNetwork: true`, `dnsPolicy: ClusterFirstWithHostNet`.
- Container port `8095` (web UI + API + zeroconf-advertised port).
- `securityContext`: default, no extra capabilities. Upstream docs mention
  `SYS_ADMIN`/`DAC_READ_SEARCH`/`apparmor:unconfined` for the case where MA
  mounts network shares itself — not needed here since the library arrives
  as a normal Kubernetes-managed PVC. Add `DAC_READ_SEARCH` later only if
  library scanning hits permission errors from NFS UID mismatches.

## Storage

Two PVCs:

- `/data` (config, sqlite db, artwork cache) — `openebs-hostpath`, RWO,
  `retain: true`, ~10Gi. Mirrors `home-assistant`'s own config-volume
  choice: local disk, avoids SQLite-on-network-share locking risk.
- `/music` (library) — new PVC on `nfs-client` (Synology-backed). Sized
  `1Ti` as a nominal PVC-API value only — `nfs-subdir-external-provisioner`
  does not enforce quota, so the Synology export grows as needed regardless
  of the requested size; no real ceiling is being imposed. RWX-capable, so
  the same export can be reached from outside the cluster later to copy
  files in.

Both PVCs must be confirmed as covered by the daily Velero backup (no entry
added to `kubernetes/apps/velero/exclusions/app/pvc-exclusions.yaml`), same
verification step used for every new PVC in this repo.

## Networking

- `HTTPRoute` for `music.68cc.io` → `traefik-internal-gateway`
  (VIP `192.168.35.17`), `authentik-forwardauth` Middleware on the UI route.
  No Cloudflare public record — LAN-only, same posture as `ha.68cc.io`.
- No bypass paths are anticipated (unlike HA, which needed `/api`/`/auth`
  bypasses for companion-app bearer tokens) since the HA↔MA integration
  talks directly over the host network via zeroconf discovery, not through
  this route. Route is for human browser access only. Revisit if MA's own
  frontend breaks behind the forwardAuth cookie flow during testing.

## Secrets

None required upfront. Tidal authentication is a PKCE browser flow
initiated from MA's own web UI after deploy — the resulting token persists
in `/data` (on the `openebs-hostpath` PVC), not as a SOPS-managed secret.

## Reloader

`reloader.stakater.com/auto: "true"` on `global.annotations` per repo
convention, even though there's no ConfigMap/Secret consumer identified yet
— cheap to have wired for whenever one is added.

## Out of scope

- Spotify or other streaming providers (Tidal only, for now).
- Populating the `/music` share with actual files — happens after deploy,
  out-of-band.
- Any change to `home-assistant`'s manifests — its integration with MA is a
  runtime UI step, not a GitOps change.
