{
  pkgs ? import <nixpkgs> { },
  lib ? pkgs.lib,
  baseURL ? null,
}:

let
  eval = import (pkgs.path + "/nixos/lib/eval-config.nix") {
    modules = [
      ../module.nix
    ];
  };

  modulePathToUrl =
    if baseURL == null then
      lib.id
    else
      path:
      if lib.hasPrefix "${toString ../.}/" path then
        let
          relPath = lib.removePrefix "${toString ../.}/" path;
          url = "${lib.removeSuffix "/" baseURL}/${relPath}";
        in
        {
          name = url;
          inherit url;
        }
      else
        path;
in
pkgs.nixosOptionsDoc {
  inherit (eval) options;
  # hide all options not declared in ../module.nix
  transformOptions =
    opt:
    opt
    // (
      if lib.all (x: x != toString ../module.nix) opt.declarations then
        {
          visible = false;
        }
      else
        {
          declarations = map modulePathToUrl opt.declarations;
        }
    );
}
