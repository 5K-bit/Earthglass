"""Bundle a prebuilt client only for the explicitly selected desktop wheel."""
import os
from pathlib import Path
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        city_data = Path(self.root) / "earthglass" / "spatial" / "data"
        if not (city_data / "cities15000.json.gz").is_file():
            raise RuntimeError("The bundled GeoNames city index is missing.")
        # The data directory is already part of the `earthglass` package, so it must not be
        # force-included as well: newer hatchling refuses a file added to the wheel twice.
        if os.environ.get("EARTHGLASS_BUNDLE_DESKTOP") != "1":
            return
        assets = Path(self.root) / "obeos-earth" / "dist"
        required = ["index.html", "cesium/Assets", "cesium/LICENSE.md", "models/aircraft.gltf"]
        if not all((assets / name).exists() for name in required):
            raise RuntimeError("Build obeos-earth with pnpm run build before making the desktop wheel.")
        build_data["force_include"][str(assets)] = "earthglass/desktop_assets"
