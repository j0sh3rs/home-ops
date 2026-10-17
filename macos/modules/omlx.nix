# oMLX: the baseline engine (spec D7). Uv-pinned (engines/omlx), run as an
# unprivileged LaunchDaemon so it serves from boot without a login (D6).
{ config, lib, pkgs, ... }:
let
  uid = 455;
  root = "/opt/ai/omlx";
  project = "/etc/home-ops/omlx";
  python = pkgs.python312;
  mainKey = config.sops.secrets."omlx/main-key".path;
  # One entry per consumer. Each needs omlx/sub-keys/<name> in
  # secrets/mac-jms-01.sops.yaml and a matching cluster Secret.
  omlxSubKeyNames = [ "gatus" ];

  env = ''
    export HOME=${root}/home
    export UV_CACHE_DIR=${root}/uv-cache
    export UV_PROJECT_ENVIRONMENT=${root}/venv
    export UV_PYTHON=${python}/bin/python3.12
    export UV_PYTHON_DOWNLOADS=never
  '';

  serve = pkgs.writeShellApplication {
    name = "omlx-serve";
    runtimeInputs = [ pkgs.uv python pkgs.git pkgs.cmake ];
    text = ''
      ${env}
      OMLX_API_KEY=$(cat ${mainKey})
      export OMLX_API_KEY
      uv sync --locked --project ${project}
      exec uv run --no-sync --project ${project} omlx serve \
        --host 0.0.0.0 \
        --port 8000 \
        --model-dir /opt/ai/models.noindex \
        --paged-ssd-cache-dir /opt/ai/kv-cache.noindex \
        --memory-guard-gb 80
    '';
  };

  subKeys = pkgs.writeShellApplication {
    name = "omlx-sub-keys";
    runtimeInputs = with pkgs; [ coreutils curl jq perl ];
    text = builtins.readFile ../scripts/omlx-sub-keys.sh;
  };
in
{
  users.knownUsers = [ "_omlx" ];
  users.knownGroups = [ "_omlx" ];
  users.groups._omlx = { gid = uid; description = "oMLX inference engine"; };
  users.users._omlx = {
    inherit uid;
    gid = uid;
    home = "${root}/home";
    createHome = false;
    shell = "/usr/bin/false";
    isHidden = true;
    description = "oMLX inference engine";
  };

  sops.defaultSopsFile = ../secrets/mac-jms-01.sops.yaml;
  sops.secrets = {
    "omlx/main-key".owner = "_omlx";
  } // lib.genAttrs (map (n: "omlx/sub-keys/${n}") omlxSubKeyNames) (_: { owner = "_omlx"; });

  environment.etc."home-ops/omlx/pyproject.toml".source = ../engines/omlx/pyproject.toml;
  environment.etc."home-ops/omlx/uv.lock".source = ../engines/omlx/uv.lock;

  # preActivation, not postActivation: the launchd step starts the daemons
  # before postActivation runs, and they need these dirs and log files at
  # first start. The users step also runs after preActivation, so _omlx may
  # not exist yet; chown by numeric uid/gid (455) instead of by name.
  system.activationScripts.preActivation.text = ''
    install -d -m 0755 -o root -g wheel /opt/ai /var/log/home-ops
    install -d -m 0750 -o ${toString uid} -g ${toString uid} ${root} ${root}/home /opt/ai/models.noindex /opt/ai/kv-cache.noindex
    for f in omlx omlx-sub-keys; do
      touch /var/log/home-ops/$f.log
      chown ${toString uid}:${toString uid} /var/log/home-ops/$f.log
    done
  '';

  launchd.daemons.omlx.serviceConfig = {
    ProgramArguments = [ "${serve}/bin/omlx-serve" ];
    UserName = "_omlx";
    GroupName = "_omlx";
    # /usr/bin for the Xcode CLT compilers uv needs when building oMLX.
    EnvironmentVariables.PATH = "/usr/bin:/bin:/usr/sbin:/sbin";
    # The engine lives in /etc/home-ops/omlx (a plain path, not a store path),
    # so a version or lock bump would not change the plist and nix-darwin
    # would not reload the daemon. Hashing the lock into the plist forces a
    # restart on every engine change.
    EnvironmentVariables.OMLX_LOCK_HASH = builtins.hashFile "sha256" ../engines/omlx/uv.lock;
    RunAtLoad = true;
    KeepAlive = true;
    ThrottleInterval = 30;
    StandardOutPath = "/var/log/home-ops/omlx.log";
    StandardErrorPath = "/var/log/home-ops/omlx.log";
  };

  launchd.daemons.omlx-sub-keys.serviceConfig = {
    ProgramArguments = [ "${subKeys}/bin/omlx-sub-keys" mainKey ]
      ++ map (n: "${n}=${config.sops.secrets."omlx/sub-keys/${n}".path}") omlxSubKeyNames;
    UserName = "_omlx";
    GroupName = "_omlx";
    RunAtLoad = true;
    StartInterval = 600;
    StandardOutPath = "/var/log/home-ops/omlx-sub-keys.log";
    StandardErrorPath = "/var/log/home-ops/omlx-sub-keys.log";
  };
}
