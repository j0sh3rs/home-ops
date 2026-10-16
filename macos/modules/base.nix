# Base system: Nix, identity, Homebrew, update policy, sshd, sops key.
{ pkgs, self, facts, ... }:
{
  nixpkgs.hostPlatform = "aarch64-darwin";

  determinateNix.enable = true;
  determinateNix.customSettings = {
    trusted-users = [ "root" facts.adminUser ];
  };

  networking.hostName = facts.hostName;
  networking.computerName = facts.hostName;
  networking.localHostName = facts.hostName;

  system.primaryUser = facts.adminUser;
  # darwin-version --json reports the commit this generation was built from
  # (null for task mac:apply-local, which builds from an untracked copy).
  system.configurationRevision = self.rev or self.dirtyRev or null;
  system.stateVersion = 6;

  environment.systemPackages = with pkgs; [ age git jq sops ];

  # Homebrew is only for things nixpkgs lacks. "zap" removes anything not
  # declared here, including by-hand installs (see the bring-up checklist).
  homebrew = {
    enable = true;
    onActivation = {
      cleanup = "zap";
      autoUpdate = false;
      upgrade = false;
    };
    brews = [ ];
    casks = [ ];
  };

  # macOS updates are a manual runbook step (docs/runbooks/mac-studio-operations.md):
  # an unattended update reboots into a FileVault-locked pre-boot screen.
  # ConfigDataInstall stays on: XProtect/Gatekeeper data, no restart.
  # Absolute path: a bare domain is written to root's home prefs, not the system plist softwareupdated reads.
  system.defaults.SoftwareUpdate.AutomaticallyInstallMacOSUpdates = false;
  system.defaults.CustomSystemPreferences = {
    "/Library/Preferences/com.apple.SoftwareUpdate" = {
      AutomaticCheckEnabled = true;
      AutomaticDownload = false;
      CriticalUpdateInstall = false;
      ConfigDataInstall = true;
    };
    "com.apple.commerce".AutoUpdate = false;
  };

  # Key-only SSH. sshd keeps the first value it reads for each keyword and
  # reads sshd_config.d/ in lexical order, so 000- beats Apple's
  # 100-macos.conf and nix-darwin's 100-nix-darwin.conf.
  services.openssh.enable = true;
  environment.etc."ssh/sshd_config.d/000-home-ops.conf".text = ''
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PermitRootLogin no
  '';

  # Mac-only age key, created by hand (bring-up checklist §8). Secrets
  # themselves are declared by the modules that use them.
  sops.age.keyFile = "/var/lib/sops-nix/key.txt";
}
