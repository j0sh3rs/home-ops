# Dedicated-server settings (spec: Server settings).
{ pkgs, ... }:
let
  # ~84 GB for GPU-wired memory. oMLX's own guard is 80 GB (omlx.nix);
  # the rest is ~12 GB for macOS and the agents. sysctl does not persist,
  # so a daemon sets it at boot and re-asserts hourly.
  wiredLimitMb = 86016;

  wiredLimit = pkgs.writeShellApplication {
    name = "home-ops-wired-limit";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      # A failed set must not skip the metric write, or the stale .prom would hide it.
      /usr/sbin/sysctl -w iogpu.wired_limit_mb=${toString wiredLimitMb} || echo "sysctl -w iogpu.wired_limit_mb failed; reporting current kernel value" >&2
      got=$(/usr/sbin/sysctl -n iogpu.wired_limit_mb)
      dir=/var/lib/node-exporter/textfile
      tmp=$(mktemp "$dir/.wired_limit.XXXXXX")
      {
        echo "# HELP home_ops_iogpu_wired_limit_bytes iogpu.wired_limit_mb currently in effect, in bytes."
        echo "# TYPE home_ops_iogpu_wired_limit_bytes gauge"
        echo "home_ops_iogpu_wired_limit_bytes $(( got * 1024 * 1024 ))"
      } > "$tmp"
      chmod 644 "$tmp"
      mv "$tmp" "$dir/home_ops_wired_limit.prom"
    '';
  };
in
{
  launchd.daemons.home-ops-wired-limit.serviceConfig = {
    ProgramArguments = [ "${wiredLimit}/bin/home-ops-wired-limit" ];
    RunAtLoad = true;
    StartInterval = 3600;
    StandardOutPath = "/var/log/home-ops/home-ops-wired-limit.log";
    StandardErrorPath = "/var/log/home-ops/home-ops-wired-limit.log";
  };

  # Never sleep; come back after a power cut (then FileVault pre-boot
  # unlock over SSH, see docs/runbooks/mac-studio-operations.md).
  power.sleep.computer = "never";
  power.sleep.harddisk = "never";
  power.sleep.display = 10;
  power.restartAfterPowerFailure = true;

  system.activationScripts.postActivation.text = ''
    /usr/bin/pmset -a powernap 0 || echo "pmset: powernap not supported"
    /usr/bin/pmset -a womp 1 || echo "pmset: womp not supported"
    # Spotlight skips any directory whose name ends in .noindex; every model
    # or KV-cache dir under /opt/ai uses that suffix (omlx.nix).
    install -d -m 0755 -o root -g wheel /opt/ai
  '';

  # Rotate our daemons' logs: keep 7, rotate at 10 MB, G = glob, N = no signal.
  environment.etc."newsyslog.d/home-ops.conf".text = ''
    # logfilename              mode count size  when flags
    /var/log/home-ops/*.log    644  7     10240 *    GN
  '';
}
