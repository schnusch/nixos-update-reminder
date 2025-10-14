{ lib, pkgs, ... }:
{
  services.nixos-update-reminder = {
    hosts =
      let
        ssh =
          host: command:
          [
            (lib.getExe pkgs.openssh)
            "-i"
            "/home/user/.ssh/key"
            host
            "--"
          ]
          ++ command;
        git_rev_parse = ref: [
          "git"
          "-C"
          "/etc/nixos/nixpkgs"
          "-c"
          "safe.directory=."
          "rev-parse"
          "--verify"
          ref
        ];
      in
      {
        localhost.argv = [
          "nixos-version"
          "--revision"
        ];
        server.argv = ssh "server" [
          "nixos-version"
          "--revision"
        ];
        testing.argv = ssh "testing" (git_rev_parse "origin/nixos-unstable");
      };
  };
}
