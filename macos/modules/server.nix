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

  # Copy-then-truncate for logs held open by always-on daemons. Keeps 3
  # generations (.0 newest). Size check every 10 min; 10 MB threshold.
  logRotate = pkgs.writeShellApplication {
    name = "home-ops-logrotate";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      max=$((10 * 1024 * 1024))
      for name in omlx omlx-exporter macmon vector; do
        f=/var/log/home-ops/$name.log
        [ -f "$f" ] || continue
        size=$(stat -c %s "$f")
        [ "$size" -ge "$max" ] || continue
        rm -f "$f.2"
        [ -f "$f.1" ] && mv "$f.1" "$f.2"
        [ -f "$f.0" ] && mv "$f.0" "$f.1"
        cp -p "$f" "$f.0"
        : > "$f"
        echo "rotated $f ($size bytes)"
      done
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

  # Always-on daemons (KeepAlive) hold their log open since launch, and
  # macOS newsyslog has no copytruncate: a rename would leave them writing to
  # the rotated file forever. home-ops-logrotate copies and truncates those in
  # place instead. Assumption (not verified against launchd source): launchd
  # opens StandardOutPath/StandardErrorPath with O_APPEND, so writes after the
  # truncate land at the new end of file rather than leaving a sparse hole.
  # vector tails *.log; a truncation is seen as a new file, at worst a few
  # lines near the cut are not shipped.
  #
  # Everything else (short-lived jobs that reopen their log every run) stays
  # on newsyslog: keep 7, rotate at 10 MB, N = no signal. Listed explicitly,
  # NOT globbed, so newsyslog never renames the files above.
  environment.etc."newsyslog.d/home-ops.conf".text = ''
    # logfilename                                  owner:group mode count size  when flags
    /var/log/home-ops/home-ops-pull.log            root:wheel   644  7     10240 *    N
    /var/log/home-ops/home-ops-wired-limit.log     root:wheel   644  7     10240 *    N
    /var/log/home-ops/pf-home-ops.log              root:wheel   644  7     10240 *    N
    /var/log/home-ops/omlx-sub-keys.log            _omlx:_omlx  644  7     10240 *    N
    /var/log/home-ops/home-ops-logrotate.log       root:wheel   644  7     10240 *    N
  '';

  launchd.daemons.home-ops-logrotate.serviceConfig = {
    ProgramArguments = [ "${logRotate}/bin/home-ops-logrotate" ];
    RunAtLoad = true;
    StartInterval = 600;
    StandardOutPath = "/var/log/home-ops/home-ops-logrotate.log";
    StandardErrorPath = "/var/log/home-ops/home-ops-logrotate.log";
  };
}
