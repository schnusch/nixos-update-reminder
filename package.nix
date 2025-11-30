{
  lib,
  buildPythonApplication,
  gobject-introspection,
  setuptools,
  wrapGAppsHook3,
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
    wrapGAppsHook3
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
