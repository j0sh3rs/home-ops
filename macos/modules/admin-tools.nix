# The admin user's interactive tooling, restored after the first switch's
# Homebrew "zap" removed everything installed by hand. CLI tools come from
# nixpkgs; Homebrew keeps only GUI casks and formulae nixpkgs lacks.
# Homebrew's zsh and the formulae's dependencies (python, openssl, aws-c-*)
# are not carried over: macOS ships /bin/zsh, which is the login shell.
{ pkgs, ... }:
{
  environment.systemPackages = with pkgs; [
    atmos
    atuin
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
    ripgrep
    starship
  ];

  homebrew = {
    taps = [
      "oleksandrkrupko/debloat"
      "steipete/tap"
    ];
    brews = [
      "oleksandrkrupko/debloat/debloat"
      "steipete/tap/imsg"
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
