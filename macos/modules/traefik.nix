# TLS edge for oMLX on the Mac Studio: https://inference.68cc.io -> 127.0.0.1:8000.
#
# Certificates come from Let's Encrypt through Traefik's built-in ACME client
# (DNS-01 on Cloudflare), using the same API token as cert-manager
# (kubernetes/apps/cert-manager/cert-manager/app/secret.sops.yaml, copied into
# secrets/mac-jms-01.sops.yaml as traefik/cloudflare-token). No public record is
# needed; the LAN A record is kubernetes/apps/ai/mac-inference/app/dnsendpoint.yaml.
#
# oMLX still checks every API key itself. It exempts loopback peers from its
# wrong-key lockout (omlx/admin/auth.py, _client_key), and behind this proxy
# every client is loopback, so the lockout never fires. The rate limit below is
# the substitute, and pf.nix limits who can reach 443 at all.
{ config, pkgs, ... }:
let
  host = "inference.68cc.io";
  stateDir = "/var/lib/traefik";
  yaml = pkgs.formats.yaml { };

  staticConfig = yaml.generate "traefik.yaml" {
    global = { checkNewVersion = false; sendAnonymousUsage = false; };
    log.level = "INFO";
    # macOS lets unprivileged processes bind 443 (since 10.14), so nobody can run this.
    entryPoints.websecure.address = ":443";
    providers.file.filename = "${dynamicConfig}";
    certificatesResolvers.letsencrypt.acme = {
      storage = "${stateDir}/acme.json";
      # The LAN resolver does not know the public _acme-challenge zone.
      dnsChallenge = { provider = "cloudflare"; resolvers = [ "1.1.1.1:53" "1.0.0.1:53" ]; };
    };
  };

  dynamicConfig = yaml.generate "traefik-dynamic.yaml" {
    http = {
      routers.omlx = {
        # API only. The admin UI (and its login) stays behind Authentik at omlx.68cc.io.
        rule = "Host(`${host}`) && PathPrefix(`/v1`)";
        entryPoints = [ "websecure" ];
        service = "omlx";
        middlewares = [ "per-client-limit" ];
        tls.certResolver = "letsencrypt";
      };
      services.omlx.loadBalancer.servers = [ { url = "http://127.0.0.1:8000"; } ];
      # Per client IP. Streamed completions count once, at the request.
      middlewares.per-client-limit.rateLimit = { average = 100; period = "1s"; burst = 200; };
    };
  };
in
{
  sops.secrets."traefik/cloudflare-token".owner = "nobody";

  launchd.daemons.traefik.serviceConfig = {
    ThrottleInterval = 30;
    ProgramArguments = [ "${pkgs.traefik}/bin/traefik" "--configFile=${staticConfig}" ];
    UserName = "nobody";
    EnvironmentVariables.CF_DNS_API_TOKEN_FILE = config.sops.secrets."traefik/cloudflare-token".path;
    RunAtLoad = true;
    KeepAlive = true;
    StandardOutPath = "/var/log/home-ops/traefik.log";
    StandardErrorPath = "/var/log/home-ops/traefik.log";
  };

  # preActivation, not postActivation: the launchd step starts the daemon before
  # postActivation runs, and it needs these at first start.
  system.activationScripts.preActivation.text = ''
    install -d -m 0700 -o nobody -g wheel ${stateDir}
    install -d -m 0755 -o root -g wheel /var/log/home-ops
    touch /var/log/home-ops/traefik.log
    chown nobody /var/log/home-ops/traefik.log
  '';
}
