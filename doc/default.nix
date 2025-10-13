{
  pkgs ? import <nixpkgs> { },
  lib ? pkgs.lib,
}:

let
  eval = import (pkgs.path + "/nixos/lib/eval-config.nix") {
    modules = [
      ../module.nix
    ];
  };
in
pkgs.nixosOptionsDoc {
  inherit (eval) options;
  # hide all options not declared in ../module.nix
  transformOptions =
    opt:
    opt
    // (lib.optionalAttrs (lib.all (x: x != toString ../module.nix) opt.declarations) {
      visible = false;
    });
}
