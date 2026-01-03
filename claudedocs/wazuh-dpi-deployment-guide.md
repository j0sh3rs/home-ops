# Wazuh DPI-Based Content Filtering Deployment Guide

**Date**: 2026-01-03
**Status**: Infrastructure Complete (Dual Protocol UDP+TCP) - Phase 1 Pending (UDM Pro Configuration)
**Commits**: 39390e2 (DPI decoder), 28af89a (decoder deployment), 12b006a (UDP conversion), 1d68fe4 (UDP guide update), 5b170df (dual protocol support)

## What Was Changed

### Phase 1: DPI Decoder and Rules (Commits 39390e2, 28af89a)

1. **Created**: `kubernetes/apps/security/wazuh/app/wazuh_managers/wazuh_conf/local_decoder.xml`
    - UDM Pro DPI decoder for parsing Deep Packet Inspection logs
    - Extracts: srcip, dstip, protocol, dpi_category, dpi_action, dpi_app, dpi_bytes

2. **Updated**: `kubernetes/apps/security/wazuh/app/wazuh_managers/wazuh_conf/local_rules.xml`
    - Rules 100020-100028 rewritten to use DPI field matching
    - YouTube detection: Streaming Media category + app name
    - Social media detection: Social Networking category
    - Gaming detection: Gaming/Online Games categories
    - Adult content: Level 15 severity, Adult Content/Pornography categories
    - High bandwidth: New rule for 1GB+ traffic detection

### Phase 2: Dual Protocol Syslog Support (Commits 12b006a, 5b170df)

**Evolution**: Initially converted from TCP-only to UDP-only (12b006a), then enhanced to support BOTH protocols simultaneously (5b170df) for maximum device compatibility.

**Infrastructure Changes**:

1. **Envoy Gateway Listeners** (`kubernetes/apps/network/envoy-gateway/app/envoy.yaml`)
    - UDP listener `wazuh-syslog-udp` on port 514 (standard RFC 3164)
    - TCP listener `wazuh-syslog-tcp` on port 514 (RFC-compliant, same port)
    - Both allowedRoutes configured for respective protocol kinds

2. **Wazuh Manager Configs** (`wazuh_conf/master.conf` and `wazuh_conf/worker.conf`)
    - UDP remote connection on port 514
    - TCP remote connection on port 514
    - Both protocols configured with 0.0.0.0/0 allowed IPs

3. **Routing Resources**:
    - `udproute.yaml`: UDPRoute for port 514 traffic
    - `wazuh-syslog-tcproute.yaml`: TCPRoute for port 514 traffic
    - Both routes target wazuh-workers service on port 514

4. **Service Configuration** (`wazuh-workers-svc.yaml`)
    - Port `syslog-udp` (514) for UDP traffic
    - Port `syslog-tcp` (514) for TCP traffic

**Traffic Flow** (Dual Protocol):

```
UDP Flow (Standard):
External Device → 192.168.35.18:514 (UDP)
  → Envoy Gateway [wazuh-syslog-udp listener]
  → UDPRoute [wazuh-syslog]
  → wazuh-workers Service (port 514)
  → wazuh-manager pods (UDP syslog listener port 514)
  → wazuh-remoted → wazuh-analysisd
  → OpenSearch (wazuh-alerts-4.x-*)

TCP Flow (Alternative):
External Device → 192.168.35.18:5140 (TCP)
  → Envoy Gateway [wazuh-syslog-tcp listener]
  → TCPRoute [wazuh-syslog-tcp]
  → wazuh-workers Service (port 5140)
  → wazuh-manager pods (TCP syslog listener port 5140)
  → wazuh-remoted → wazuh-analysisd
  → OpenSearch (wazuh-alerts-4.x-*)
```

## Deployment Steps

### Step 1: Push Changes to Repository

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops
git push origin main
```

### Step 2: Reconcile FluxCD (Force Immediate Deployment)

```bash
flux reconcile ks wazuh -n security --with-source --context home
```

This will:

1. Pull latest changes from Git
2. Regenerate wazuh-manager-conf ConfigMap with updated decoder and rules
3. Restart Wazuh manager pods to load new configuration

### Step 3: Verify Configuration Deployment

```bash
# Check ConfigMap includes new decoder
kubectl get configmap wazuh-manager-conf -n security --context home -o yaml | grep -A 5 "local_decoder.xml"

# Check manager pods restarted
kubectl get pods -n security -l app=wazuh-manager --context home

# Verify decoder loaded (check manager logs)
kubectl logs -n security wazuh-manager-worker-0 --context home | grep -i "decoder.*udmpro-dpi"
```

Expected: Manager logs should show decoder loaded without errors.

## UDM Pro Configuration (Phase 1) - **ACTION REQUIRED**

**CRITICAL**: Wazuh is now configured to parse DPI logs, but UDM Pro must be configured to send them.

### Important: Understanding UnifiOS Logging Features

UnifiOS has **multiple logging features** that are often confused:

1. **Flow Logging (NetFlow/IPFIX)** ❌ WRONG FEATURE
    - Location: Settings → System → Traffic Logging → NetFlow
    - Port: 2055
    - Purpose: Flow statistics for local dashboard viewing
    - **Does NOT send DPI application logs to syslog**

2. **CyberSecure Traffic Logging** ✅ THIS IS WHAT YOU NEED
    - Location: Settings → CyberSecure → Traffic Logging
    - Port: 514 (syslog)
    - Purpose: DPI-classified application logs to external SIEM
    - **Sends DPI categories (YouTube, Facebook, gaming) to syslog**

3. **Control Plane Activity Logging** ❌ WRONG FEATURE
    - Location: Settings → Control Plane → Integrations
    - Port: 9003
    - Purpose: System/admin events in CEF format
    - **Does NOT send DPI application logs**

### Step 1: Enable Traffic Identification (DPI)

1. Open UniFi Network Console: https://192.168.35.1
2. Navigate to: **Settings → System → Advanced**
3. Enable both features:
    - **Traffic Identification**: ON (this is DPI for applications)
    - **Device Identification**: ON (this is DPI for devices)

### Step 2: Configure CyberSecure Traffic Logging (SIEM Integration)

**This is the critical configuration that sends DPI logs to Wazuh:**

1. Navigate to: **Settings → CyberSecure → Traffic Logging**

2. Enable SIEM Server:
    - **Enable SIEM Server**: ✅ (toggle ON)
    - **Server Address**: `192.168.35.18`
    - **Port**: Choose one:
        - `514` for UDP (recommended - standard RFC 3164)
        - `5140` for TCP (alternative for devices requiring TCP)
    - **Protocol**: **UDP** or **TCP** (both supported)
    - **Log Format**: CEF (optional - Wazuh decoder handles both formats)

**Protocol Recommendations**:

- **UDP (port 514)**: Standard syslog protocol (RFC 3164), recommended for most devices
- **TCP (port 5140)**: Alternative for devices that require reliable delivery or are incompatible with UDP
- **Both Supported**: Wazuh infrastructure accepts both protocols simultaneously

3. Enable Traffic Categories (select which DPI events to log):
    - **Security Detections**: ✅
    - **Firewall Events**: ✅
    - **IDS/IPS Events**: ✅
    - **Application Control**: ✅

4. Save configuration

**Note**: This replaces the outdated "Traffic Rules" approach. Modern UnifiOS uses CyberSecure section for SIEM integration.

## Testing and Verification

### Step 1: Wait for DPI Logs

After enabling DPI and Traffic Rules, wait 5-10 minutes for traffic patterns to be classified.

### Step 2: Check Raw DPI Logs in Wazuh

Query OpenSearch for DPI logs:

```
Dashboard: https://wazuh.68cc.io
Navigate: Discover
Index: wazuh-alerts-*
Query: data.dpi_category:*
Time: Last 1 hour
```

Expected log format:

```
Jan 02 13:45:23 udm-jms-01 [DPI] src=192.168.35.100:54321 dst=142.250.80.78:443 proto=tcp category="Social Networking" action=allow app="Facebook" bytes=4567
```

### Step 3: Generate Test Traffic

From a user device on the network:

1. Visit facebook.com or instagram.com (Social Networking)
2. Watch a YouTube video (Streaming Media)
3. Play an online game (Gaming)

### Step 4: Verify Content Filtering Alerts

Check Wazuh alerts:

```
Dashboard: https://wazuh.68cc.io
Navigate: Security events
Filter: rule.groups: "content_monitoring"
Time: Last 1 hour
```

Expected alerts:

- **Rule 100021**: "Content Filter: YouTube streaming detected"
- **Rule 100023**: "Content Filter: Social media access detected"
- **Rule 100024**: "Content Filter: Online gaming detected"

Alert details should show:

- **srcip**: User device IP (e.g., 192.168.35.100)
- **dpi_app**: Application name (e.g., "YouTube", "Facebook")
- **dpi_category**: Category (e.g., "Streaming Media", "Social Networking")

### Step 5: Test High Bandwidth Detection

Stream a 4K video or download a large file to trigger rule 100028 (1GB+ traffic).

Query:

```
Filter: rule.id: "100028"
```

Expected: Alert showing high traffic volume with dpi_bytes field.

## Troubleshooting

### Problem: No DPI logs appearing in Wazuh

**Check 1 - DPI Enabled on UDM Pro**:

```bash
# SSH to UDM Pro
ssh admin@192.168.35.1

# Check DPI status
ubnt-dpi-tool status
```

Expected: "DPI is enabled"

**Check 2 - Traffic Rules Configured**:

- Verify Traffic Rules exist with "Enable Logging" checked
- Rules must match actual traffic (test with Facebook, YouTube, etc.)

**Check 3 - Syslog Connection**:

```bash
# Check UDM Pro syslog configuration
cat /etc/rsyslog.d/49-dpi.conf
```

Expected: Should contain UDP forwarding rule to `192.168.35.18:514` (Envoy Gateway)

**Note**: The `@` prefix indicates UDP protocol, while `@@` would indicate TCP. Wazuh infrastructure is configured for UDP syslog.

If missing, add:

```bash
# Add DPI log forwarding via UDP (@ = UDP, @@ = TCP)
echo '*.* @192.168.35.18:514' > /etc/rsyslog.d/49-dpi.conf
systemctl restart rsyslog
```

### Problem: DPI logs appear but no alerts triggered

**Check 1 - Decoder Loaded**:

```bash
kubectl logs -n security wazuh-manager-worker-0 --context home | grep -i "decoder.*udmpro-dpi"
```

Expected: "Decoder 'udmpro-dpi' loaded"

**Check 2 - Log Format Match**:

Capture actual DPI log format:

```bash
# Query OpenSearch for raw syslog message
Dashboard → Discover → Search: "[DPI]"
```

Compare actual format to expected format in decoder regex. If format differs, decoder regex needs adjustment.

**Check 3 - Rule Field Matching**:

Verify DPI category names match UDM Pro output:

- Expected: "Social Networking", "Streaming Media", "Gaming", "Adult Content"
- If UDM Pro uses different names (e.g., "Social Media" instead of "Social Networking"), update rules accordingly

### Problem: Alerts trigger but incorrect severity or descriptions

**Solution**: Tune rules in `local_rules.xml`:

- Adjust severity levels (currently: YouTube=8, Social=7, Gaming=6, Adult=15)
- Update field matching regex if DPI app names differ
- Add additional DPI categories if needed

After changes:

```bash
git commit -m "fix(wazuh): tune content filtering rules"
git push
flux reconcile ks wazuh -n security --with-source --context home
```

## Discord Integration Next Steps

Once content filtering is working:

1. **Provide Discord Webhook URL**: Replace PLACEHOLDER_DISCORD_WEBHOOK_URL in wazuh-secrets
2. **Deploy Integration**: `flux reconcile ks wazuh -n security --with-source --context home`
3. **Test Alert Delivery**: Generate test alert, verify Discord notification

See `claudedocs/wazuh-discord-integration-complete.md` for Discord setup details.

## Success Criteria

✅ **Phase 2 Complete** (Wazuh Configuration):

- [x] UDM Pro DPI decoder created
- [x] Content filtering rules updated to use DPI fields
- [x] Changes committed to repository
- [x] Configuration deployed via FluxCD

⏳ **Phase 1 Pending** (UDM Pro Configuration):

- [ ] Deep Packet Inspection enabled on UDM Pro
- [ ] Traffic Rules created with logging for: Social Networking, Streaming Media, Gaming, Adult Content
- [ ] DPI logs visible in Wazuh OpenSearch

⏳ **Phase 3 Pending** (Testing):

- [ ] Test traffic generated (Facebook, YouTube, gaming)
- [ ] Content filtering alerts visible in dashboard
- [ ] Alert details show correct srcip, dpi_app, dpi_category
- [ ] High bandwidth detection working (rule 100028)
- [ ] After-hours detection working (rule 100027)

## Expected Alert Examples

### YouTube Alert (Rule 100021, Level 8)

```
Title: Content Filter: YouTube streaming detected
Description: App: YouTube Src: 192.168.35.100
Severity: High (Level 8)
Groups: youtube_video, streaming_media, content_monitoring
Fields:
  - srcip: 192.168.35.100
  - dpi_app: YouTube
  - dpi_category: Streaming Media
```

### Social Media Alert (Rule 100023, Level 7)

```
Title: Content Filter: Social media access detected
Description: App: Facebook Src: 192.168.35.100
Severity: Medium (Level 7)
Groups: social_media_access, content_monitoring
Fields:
  - srcip: 192.168.35.100
  - dpi_app: Facebook
  - dpi_category: Social Networking
```

### Adult Content Alert (Rule 100025, Level 15)

```
Title: Content Filter: ADULT CONTENT ACCESS DETECTED
Description: App: [detected_app] Src: 192.168.35.100 - IMMEDIATE ATTENTION
Severity: Critical (Level 15)
Groups: adult_content, content_monitoring, critical_alert
Fields:
  - srcip: 192.168.35.100
  - dpi_app: [detected_app]
  - dpi_category: Adult Content
```

## Limitations

1. **No YouTube Video URL Paths**: DPI identifies YouTube app but not specific video URLs (HTTPS encryption)
2. **SNI-Based Classification**: DPI uses Server Name Indication for HTTPS traffic classification
3. **Category Accuracy**: Depends on UDM Pro DPI classification database accuracy
4. **Performance Impact**: DPI may add 1-5ms latency to network traffic
5. **False Positives/Negatives**: Some traffic may be misclassified (e.g., educational YouTube vs entertainment)

## Reference Documentation

- **UDM Pro DPI Guide**: `claudedocs/wazuh-udm-pro-logging-configuration.md`
- **Wazuh Rules Syntax**: https://documentation.wazuh.com/current/user-manual/ruleset/ruleset-xml-syntax/rules.html
- **Wazuh Decoder Syntax**: https://documentation.wazuh.com/current/user-manual/ruleset/ruleset-xml-syntax/decoders.html
- **Discord Integration**: `claudedocs/wazuh-discord-integration-complete.md`
