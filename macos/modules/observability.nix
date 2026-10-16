# Host, GPU/power, engine metrics and logs (spec: Observability).
# Scraped through kubernetes/apps/ai/mac-inference (VMStaticScrape).
{ config, lib, pkgs, ... }:
let
  # macmon < 0.10.0 reads zero CPU/ANE power on macOS 27; fall back to
  # Homebrew's (current) formula until nixpkgs catches up.
  nixMacmon = lib.versionAtLeast pkgs.macmon.version "0.10.0";
  macmonBin = if nixMacmon then "${pkgs.macmon}/bin/macmon" else "/opt/homebrew/bin/macmon";

  omlxExporter = pkgs.writers.writePython3Bin "omlx-exporter" { flakeIgnore = [ "E501" ]; }
    (builtins.readFile ../pkgs/omlx-exporter/omlx_exporter.py);

  vectorConfig = (pkgs.formats.yaml { }).generate "vector.yaml" {
    data_dir = "/var/lib/vector";
    sources.files = {
      type = "file";
      include = [ "/var/log/home-ops/*.log" ];
      # vector's own log would feed its sink retries back into itself.
      exclude = [ "/var/log/home-ops/vector.log" ];
    };
    transforms.tag = {
      type = "remap";
      inputs = [ "files" ];
      source = ''
        .hostname = "mac-jms-01"
        .stream = "mac-jms-01"
        .app_name = replace(replace(string!(.file), r'^.*/', ""), r'\.log$', "")
      '';
    };
    # Same ingest path and headers as the cluster's vector
    # (kubernetes/apps/monitoring/vector/app/helmrelease.yaml).
    sinks.vlogs = {
      type = "elasticsearch";
      inputs = [ "tag" ];
      endpoints = [ "https://logs.68cc.io/insert/elasticsearch/" ];
      mode = "bulk";
      api_version = "v8";
      compression = "zstd";
      healthcheck.enabled = false;
      buffer = { type = "disk"; max_size = 268435488; when_full = "block"; };
      request.headers = {
        VL-Time-Field = "timestamp";
        VL-Stream-Fields = "stream,app_name,hostname";
        VL-Msg-Field = "message";
        AccountID = "0";
        ProjectID = "0";
      };
    };
  };
in
{
  services.prometheus.exporters.node = {
    enable = true;
    port = 9100;
    extraFlags = [ "--collector.textfile.directory=/var/lib/node-exporter/textfile" ];
  };

  homebrew.brews = lib.optional (!nixMacmon) "macmon";

  launchd.daemons.macmon.serviceConfig = {
    ThrottleInterval = 30;
    ProgramArguments = [ macmonBin "serve" "--port" "9090" ];
    UserName = "nobody";
    RunAtLoad = true;
    KeepAlive = true;
    StandardOutPath = "/var/log/home-ops/macmon.log";
    StandardErrorPath = "/var/log/home-ops/macmon.log";
  };

  launchd.daemons.omlx-exporter.serviceConfig = {
    ThrottleInterval = 30;
    ProgramArguments = [
      "${omlxExporter}/bin/omlx-exporter"
      "--listen-port" "9101"
      "--api-key-file" config.sops.secrets."omlx/main-key".path
    ];
    UserName = "_omlx";
    GroupName = "_omlx";
    RunAtLoad = true;
    KeepAlive = true;
    StandardOutPath = "/var/log/home-ops/omlx-exporter.log";
    StandardErrorPath = "/var/log/home-ops/omlx-exporter.log";
  };

  launchd.daemons.vector.serviceConfig = {
    ThrottleInterval = 30;
    ProgramArguments = [ "${pkgs.vector}/bin/vector" "--config" "${vectorConfig}" ];
    RunAtLoad = true;
    KeepAlive = true;
    StandardOutPath = "/var/log/home-ops/vector.log";
    StandardErrorPath = "/var/log/home-ops/vector.log";
  };

  # preActivation, not postActivation: the launchd step starts the daemons
  # before postActivation runs, and they need these at first start. The users
  # step also runs later, so _omlx may not exist yet; chown by numeric id
  # (455, same as modules/omlx.nix). macmon runs as nobody.
  system.activationScripts.preActivation.text = ''
    install -d -m 0700 -o root -g wheel /var/lib/vector
    install -d -m 0755 -o root -g wheel /var/log/home-ops
    for f in macmon omlx-exporter; do touch /var/log/home-ops/$f.log; done
    chown nobody /var/log/home-ops/macmon.log
    chown 455:455 /var/log/home-ops/omlx-exporter.log
  '';
}
