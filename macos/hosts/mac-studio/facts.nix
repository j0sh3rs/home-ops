# Non-secret facts about the Mac Studio, recorded during manual bring-up
# (docs/runbooks/mac-studio-bringup.md §9). The Mac's IP is also in
# kubernetes/apps/ai/mac-inference/app/service.yaml (EndpointSlice) and
# nowhere else.
{
  hostName = "mac-studio";
  adminUser = "ADMIN_USER";
  lanIp = "MAC_IP";
  # Cluster node IPs. Cilium masquerades pod egress to the node IP, so these
  # are the only sources pf has to admit. bigboi-jms-01 (.4) leaves at
  # spec Phase 3.5 -- remove it here in that change.
  clusterNodeIps = [
    "192.168.35.3"  # bee-jms-01
    "192.168.35.6"  # bee-jms-02
    "192.168.35.10" # bee-jms-03
    "192.168.35.4"  # bigboi-jms-01
  ];
}
