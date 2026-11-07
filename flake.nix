{
  description = "http-mcp development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python313
            uv
            git
          ];

          shellHook = ''
            if [ -d .venv ]; then
              source .venv/bin/activate
              uv sync
            else
              uv venv --python 3.13
              source .venv/bin/activate
            fi

            echo "Setting git hooksPath to .githooks"
            chmod +x .githooks/pre-push
            git config core.hooksPath .githooks
          '';
        };
      });
}
