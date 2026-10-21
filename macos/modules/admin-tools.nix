# The admin user's interactive tooling, restored after the first switch's
# Homebrew "zap" removed everything installed by hand.
# Interactive CLI tools the admin uses day to day come from Homebrew, which
# tracks upstream releases closely. nixpkgs' 26.05 atuin (18.15) lagged the
# history DB's migrations and broke every shell start, so atuin, starship and
# ripgrep moved here from nixpkgs. Anything a system module needs at a fixed
# store path (age, git, jq in base.nix) stays in nixpkgs.
# Homebrew's zsh is installed but /bin/zsh remains the login shell.
{ pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    atmos
    awscli2
    fd
    fluxcd
    fzf
    gh
    hyperfine
    kubectl
    kubectx
    kubernetes-helm
    mise
  ];

  homebrew = {
    taps = [
      "oleksandrkrupko/debloat"
      "steipete/tap"
    ];
    brews = [
      "oleksandrkrupko/debloat/debloat"
      "steipete/tap/imsg"
      "actionlint"
      "age"
      "atuin"
      "autoconf"
      "automake"
      "bash"
      # bash-completion is the bash 3.2 line; @2 is the one for Homebrew's bash 5.
      "bash-completion@2"
      "bash-language-server"
      "cython"
      "gcc"
      "git"
      "git-extras"
      "hadolint"
      "jq"
      "markdownlint-cli"
      "pre-commit"
      "ripgrep"
      "rtk"
      "shellcheck"
      "starship"
      "terraform-docs"
      "velero"
      "yaml-language-server"
      "yamllint"
      "zsh"
    ];
    casks = [
      # The cask tracks Anthropic's latest release; nixpkgs' claude-code lags.
      "claude-code@latest"
      "firefox"
      "ghostty"
      "iterm2"
      "orbstack"
    ];
  };
}
