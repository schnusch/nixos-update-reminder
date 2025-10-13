{
  lib,
  buildPythonApplication,
  gobject-introspection,
  setuptools,
  wrapGAppsHook,
  libnotify,
  pygobject3,
}:

let

  src = lib.sourceByRegex ./. [
    "COPYING\\.md"
    "pyproject\\.toml"
    ".*\\.py"
  ];

  pyproject = with builtins; fromTOML (readFile "${src}/pyproject.toml");

in

buildPythonApplication {
  pname = pyproject.project.name;
  inherit (pyproject.project) version;

  inherit src;

  format = "pyproject";

  nativeBuildInputs = [
    wrapGAppsHook
    gobject-introspection
  ];

  buildInputs = [
    setuptools
  ];

  dependencies = [
    libnotify
    pygobject3
  ];

  meta = {
    description = pyproject.project.description;
    homepage = pyproject.project.urls.homepage;
    license = lib.licenses.beerware;
    maintainers = with lib.maintainers; [ schnusch ];
    mainProgram = "nixos-update-reminder";
  };
}
