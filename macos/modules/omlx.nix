# oMLX access: the main key the oMLX exporter logs in with, and the `_omlx`
# account that exporter runs as.
#
# The engine itself is NOT managed here. The nix-managed oMLX daemon, its
# model-settings and sub-key reconcilers and the pinned engine project were
# removed on 2026-11-13: the user-run oMLX app is the canonical instance
# (docs/research/2026-11-13-omlx-splash-model-evaluation/, runbook
# docs/runbooks/mac-studio-operations.md "oMLX (user-run app)").
# `omlx/main-key` must therefore hold the main API key of that app instance.
{ ... }:
let
  uid = 455;
in
{
  users.knownUsers = [ "_omlx" ];
  users.knownGroups = [ "_omlx" ];
  users.groups._omlx = { gid = uid; description = "oMLX inference engine"; };
  users.users._omlx = {
    inherit uid;
    gid = uid;
    home = "/opt/ai/omlx/home";
    createHome = false;
    shell = "/usr/bin/false";
    isHidden = true;
    description = "oMLX inference engine";
  };

  sops.defaultSopsFile = ../secrets/mac-jms-01.sops.yaml;
  sops.secrets."omlx/main-key".owner = "_omlx";

  # preActivation, not postActivation: the launchd step starts the daemons
  # before postActivation runs, and they need the log directory at first start
  # (observability.nix creates the individual log files).
  system.activationScripts.preActivation.text = ''
    install -d -m 0755 -o root -g wheel /var/log/home-ops
  '';
}
