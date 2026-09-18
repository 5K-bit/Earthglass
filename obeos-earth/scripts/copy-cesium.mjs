import { cpSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const sourceRoot = resolve("node_modules/cesium/Build/Cesium");
const destinationRoot = resolve("dist/cesium");

mkdirSync(destinationRoot, { recursive: true });
for (const directory of ["Assets", "ThirdParty", "Widgets", "Workers"]) {
  cpSync(resolve(sourceRoot, directory), resolve(destinationRoot, directory), {
    recursive: true,
  });
}

for (const name of ["LICENSE.md", "ThirdParty.json", "ThirdParty.extra.json"]) {
  cpSync(resolve("node_modules/cesium", name), resolve(destinationRoot, name));
}

for (const name of ["react", "react-dom"]) {
  cpSync(
    resolve("node_modules", name, "LICENSE"),
    resolve("dist", name + "-LICENSE.txt"),
  );
}
