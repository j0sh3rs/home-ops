{
  description = "home-ops macOS hosts (nix-darwin). Applied by the pull loop in modules/pull-loop.nix.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";
    nix-darwin = {
      url = "github:nix-darwin/nix-darwin/nix-darwin-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # Determinate owns the Nix daemon and nix.conf; its module replaces
    # nix-darwin's nix.* management (determinateNix.*, needs Determinate Nix >= 3.15.2).
    determinate.url = "https://flakehub.com/f/DeterminateSystems/determinate/3";
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nix-darwin, determinate, sops-nix, ... }: {
    darwinConfigurations.mac-studio = nix-darwin.lib.darwinSystem {
      specialArgs = {
        inherit self;
        facts = import ./hosts/mac-studio/facts.nix;
      };
      modules = [
        determinate.darwinModules.default
        sops-nix.darwinModules.sops
        ./hosts/mac-studio
      ];
    };
  };
}
