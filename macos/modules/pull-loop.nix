# Pull loop: apply main every time it moves (scripts/home-ops-pull.sh).
{ pkgs, ... }:
let
  pull = pkgs.writeShellApplication {
    name = "home-ops-pull";
    runtimeInputs = with pkgs; [ coreutils git ];
    text = builtins.readFile ../scripts/home-ops-pull.sh;
  };
in
{
  environment.systemPackages = [ pull ];

  # preActivation, not postActivation: the launchd step loads daemons that
  # log or write under these dirs, and it runs before postActivation.
  system.activationScripts.preActivation.text = ''
    install -d -m 0755 -o root -g wheel /var/log/home-ops /var/lib/node-exporter/textfile /var/lib/home-ops-pull
  '';

  launchd.daemons.home-ops-pull.serviceConfig = {
    # Through the system profile, not a store path: a script change must not
    # change this plist. nix-darwin reloads a daemon whose plist changed,
    # and reloading this one would kill the darwin-rebuild it is running.
    # Changes to this block itself: apply with `task mac:apply-local`.
    ProgramArguments = [ "/bin/sh" "-c" "exec /run/current-system/sw/bin/home-ops-pull" ];
    EnvironmentVariables.PATH = "/run/current-system/sw/bin:/nix/var/nix/profiles/default/bin:/usr/bin:/bin:/usr/sbin:/sbin";
    RunAtLoad = true;
    StartInterval = 300;
    StandardOutPath = "/var/log/home-ops/home-ops-pull.log";
    StandardErrorPath = "/var/log/home-ops/home-ops-pull.log";
  };
}
