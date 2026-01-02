#!/usr/bin/env python3
"""
Wazuh Discord Integration Script
Sends Wazuh alerts to Discord via webhook with formatted embeds.

This script is called by Wazuh's integratord daemon when alerts match
the configured criteria. It receives alert data as JSON and formats it
as a Discord embed with color coding and detailed information.

Configuration in ossec.conf:
  <integration>
    <name>custom-discord</name>
    <api_key>WAZUH_DASHBOARD_URL</api_key>
    <hook_url>DISCORD_WEBHOOK_URL</hook_url>
    <alert_format>json</alert_format>
  </integration>
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime


def get_alert_color(level):
    """
    Determine Discord embed color based on alert severity.

    Args:
        level: Alert severity level (integer)

    Returns:
        int: Discord color code in decimal format
    """
    # Yellow (0xFFFF00 = 16776960) for level <= 5
    # Red (0xFF0000 = 16711680) for level > 5
    if level <= 5:
        return 16776960  # Yellow
    else:
        return 16711680  # Red


def format_alert(alert_json, dashboard_url):
    """
    Format Wazuh alert as Discord embed.

    Args:
        alert_json: Parsed alert data from Wazuh
        dashboard_url: URL to Wazuh dashboard

    Returns:
        dict: Discord webhook payload with formatted embed
    """
    # Extract alert details with safe defaults
    rule = alert_json.get("rule", {})
    agent = alert_json.get("agent", {})

    # Basic alert information
    rule_id = rule.get("id", "N/A")
    rule_level = rule.get("level", 0)
    rule_description = rule.get("description", "No description")

    # Agent information
    agent_id = agent.get("id", "N/A")
    agent_name = agent.get("name", "N/A")

    # Timestamp
    timestamp = alert_json.get("timestamp", datetime.utcnow().isoformat())

    # Build embed fields
    fields = [
        {"name": "🔍 Rule ID", "value": f"`{rule_id}`", "inline": True},
        {"name": "⚠️ Severity Level", "value": f"`{rule_level}`", "inline": True},
        {
            "name": "🖥️ Agent",
            "value": f"`{agent_name}` (ID: {agent_id})",
            "inline": False,
        },
    ]

    # Add MITRE ATT&CK information if available
    mitre = rule.get("mitre", {})
    if mitre:
        techniques = mitre.get("technique", [])
        tactics = mitre.get("tactic", [])

        if techniques:
            fields.append(
                {
                    "name": "🎯 MITRE ATT&CK Techniques",
                    "value": ", ".join([f"`{t}`" for t in techniques]),
                    "inline": False,
                }
            )

        if tactics:
            fields.append(
                {
                    "name": "🎯 MITRE ATT&CK Tactics",
                    "value": ", ".join([f"`{t}`" for t in tactics]),
                    "inline": False,
                }
            )

    # Add compliance information if available
    compliance = {}
    if "gdpr" in rule:
        compliance["GDPR"] = ", ".join(rule["gdpr"])
    if "pci_dss" in rule:
        compliance["PCI DSS"] = ", ".join(rule["pci_dss"])
    if "hipaa" in rule:
        compliance["HIPAA"] = ", ".join(rule["hipaa"])
    if "nist_800_53" in rule:
        compliance["NIST 800-53"] = ", ".join(rule["nist_800_53"])

    if compliance:
        compliance_text = "\n".join([f"**{k}**: {v}" for k, v in compliance.items()])
        fields.append(
            {"name": "📋 Compliance", "value": compliance_text, "inline": False}
        )

    # Add full log if available
    full_log = alert_json.get("full_log", "")
    if full_log:
        # Truncate if too long (Discord field limit is 1024 characters)
        if len(full_log) > 900:
            full_log = full_log[:900] + "..."
        fields.append(
            {"name": "📝 Full Log", "value": f"```\n{full_log}\n```", "inline": False}
        )

    # Dashboard link (if agent has events)
    dashboard_link = (
        f"{dashboard_url}/app/wazuh#/overview/?tab=general&agentId={agent_id}"
    )

    # Build Discord embed
    embed = {
        "title": f"🚨 {rule_description}",
        "color": get_alert_color(rule_level),
        "fields": fields,
        "footer": {"text": f"Wazuh Security Alert • {timestamp}"},
        "url": dashboard_link,
    }

    return {"embeds": [embed]}


def main():
    """
    Main function to process Wazuh alert and send to Discord.

    Reads alert JSON from stdin, formats it, and sends to Discord webhook.
    """
    try:
        # Read alert JSON from stdin (provided by Wazuh integratord)
        alert_file = sys.stdin.read()
        alert_json = json.loads(alert_file)

        # Extract integration configuration
        # These are passed by Wazuh from the <integration> config
        integration = alert_json.get("integration", {})
        dashboard_url = integration.get(
            "api_key", "https://wazuh.68cc.io"
        )  # api_key field used for dashboard URL
        webhook_url = integration.get("hook_url", "")

        if not webhook_url:
            sys.stderr.write("ERROR: Discord webhook URL not configured\n")
            sys.exit(1)

        # Format alert as Discord embed
        payload = format_alert(alert_json, dashboard_url)

        # Prepare request
        payload_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Wazuh-Discord-Integration/1.0",
            },
            method="POST",
        )

        # Send to Discord
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                # Discord returns 204 No Content on success
                if response.status in (200, 204):
                    sys.exit(0)
                else:
                    response_text = response.read().decode("utf-8")
                    sys.stderr.write(
                        f"ERROR: Discord webhook returned {response.status}: {response_text}\n"
                    )
                    sys.exit(1)
        except urllib.error.HTTPError as e:
            # HTTP errors (4xx, 5xx)
            error_body = e.read().decode("utf-8") if e.fp else "No error body"
            sys.stderr.write(
                f"ERROR: Discord webhook returned {e.code}: {error_body}\n"
            )
            sys.exit(1)
        except urllib.error.URLError as e:
            # Network errors (DNS, connection, timeout)
            sys.stderr.write(f"ERROR: Failed to connect to Discord: {e.reason}\n")
            sys.exit(1)

    except json.JSONDecodeError as e:
        sys.stderr.write(f"ERROR: Failed to parse alert JSON: {e}\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"ERROR: Unexpected error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
