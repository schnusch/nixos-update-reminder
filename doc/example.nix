{ pkgs, ... }:
{
  imports = [
    "${
      builtins.fetchTarball {
        url = "https://github.com/schnusch/nixos-update-reminder/archive/@@commit@@.tar.gz";
        sha256 = "@@sha256@@";
      }
    }/module.nix"
  ];
  services.nixos-update-reminder = {
    enable = true;
    user = "user"; # your username
  };
}
