{
  config,
  lib,
  pkgs,
  utils,
  ...
}:
with lib;
let
  cfg = config.services.nixos-update-reminder;

  format = pkgs.formats.toml { };
  configFile = format.generate "nixos-update-reminder.toml" (
    filterAttrs (k: v: v != null) cfg.settings
  );

  timespanType =
    with types;
    nullOr (oneOf [
      int
      str
    ]);

  settingsOptions = {
    max_time_since_update = mkOption {
      description = "Display a notification if the NixOS revision is older than this age.";
      type = timespanType;
      default = null;
      example = "1w";
    };

    # We do not need notification_interval, the systemd timer takes care of that.

    nixos_version_timeout = mkOption {
      description = "Abort host commands after this timeout.";
      type = timespanType;
      default = null;
      example = 30;
    };

    http_timeout = mkOption {
      description = "Abort GitHub API calls after this timeout.";
      type = timespanType;
      default = null;
      example = 30;
    };

    hosts = mkOption {
      description = "Commands that query the NixOS revision.";
      default = {
        localhost.argv = [
          "echo"
          config.system.nixos.revision
        ];
      };
      defaultText = literalExpression ''
        {
          # nixos-version is only added to environment.systemPackages and
          # not available through pkgs, but we can imitate nixos-version.
          localhost.argv = [ "echo" config.system.nixos.revision ];
        }
      '';
      type =
        with types;
        attrsOf (submodule {
          options = hostOptions;
        });
    };
  };

  hostOptions = {
    argv = mkOption {
      description = ''
        Command executed to query the NixOS revision. It must print the commit
        on the first line to its stdout.
      '';
      type = with types; listOf str;
      example = [
        "nixos-version"
        "--revision"
      ];
    };
  };
in
{
  options = {
    services.nixos-update-reminder = {
      enable = mkEnableOption "nixos-update-reminder";

      package = mkOption {
        description = "The nixos-update-reminder package to use.";
        type = types.package;
        default = pkgs.python3.pkgs.callPackage ./package.nix { };
        defaultText = literalExpression "pkgs.python3.pkgs.callPackage ./package.nix { }";
      };

      user = mkOption {
        description = "User to run nixos-update-reminder as.";
        type = types.str;
      };

      timerConfig = utils.systemdUtils.unitOptions.timerOptions.options.timerConfig // {
        description = "The timer configuration for nixos-update-reminder.";
        default = {
          OnStartupSec = "2min";
          OnUnitActiveSec = "1h";
        };
      };

      settings = settingsOptions;
    };
  };

  config = mkIf cfg.enable {
    systemd.user.services.nixos-update-reminder = {
      description = "NixOS Update Reminder";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${getExe cfg.package} -fc ${configFile}";
        Restart = "on-failure";
      };
    };

    systemd.user.timers.nixos-update-reminder = {
      wantedBy = [ "timers.target" ];
      unitConfig = {
        ConditionUser = cfg.user;
      };
      inherit (cfg) timerConfig;
    };
  };
}
