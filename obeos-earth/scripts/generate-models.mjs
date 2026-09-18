// Original OBEOS generic symbols. No downloaded aircraft, vessel or satellite models.
import { mkdirSync, writeFileSync } from "node:fs";
const face = [
  [
    [1, 0, 0],
    [1, -1, -1],
    [1, 1, -1],
    [1, 1, 1],
    [1, -1, 1],
  ],
  [
    [-1, 0, 0],
    [-1, -1, 1],
    [-1, 1, 1],
    [-1, 1, -1],
    [-1, -1, -1],
  ],
  [
    [0, 1, 0],
    [-1, 1, -1],
    [-1, 1, 1],
    [1, 1, 1],
    [1, 1, -1],
  ],
  [
    [0, -1, 0],
    [-1, -1, 1],
    [-1, -1, -1],
    [1, -1, -1],
    [1, -1, 1],
  ],
  [
    [0, 0, 1],
    [-1, -1, 1],
    [1, -1, 1],
    [1, 1, 1],
    [-1, 1, 1],
  ],
  [
    [0, 0, -1],
    [1, -1, -1],
    [-1, -1, -1],
    [-1, 1, -1],
    [1, 1, -1],
  ],
];
function model(name, boxes, color) {
  const positions = [],
    normals = [];
  for (const [cx, cy, cz, sx, sy, sz] of boxes)
    for (const [normal, ...corners] of face)
      for (const i of [0, 1, 2, 0, 2, 3]) {
        const p = corners[i];
        positions.push(
          cx + (p[0] * sx) / 2,
          cy + (p[1] * sy) / 2,
          cz + (p[2] * sz) / 2,
        );
        normals.push(...normal);
      }
  const p = new Float32Array(positions),
    n = new Float32Array(normals),
    buffer = Buffer.concat([Buffer.from(p.buffer), Buffer.from(n.buffer)]);
  const min = [0, 1, 2].map((axis) =>
    Math.min(...positions.filter((_, i) => i % 3 === axis)),
  );
  const max = [0, 1, 2].map((axis) =>
    Math.max(...positions.filter((_, i) => i % 3 === axis)),
  );
  const gltf = {
    asset: {
      version: "2.0",
      generator: "OBEOS generic symbols",
      copyright:
        "Original OBEOS model; generic visualization, not an identified vehicle",
    },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0 }],
    meshes: [
      { primitives: [{ attributes: { POSITION: 0, NORMAL: 1 }, material: 0 }] },
    ],
    materials: [
      {
        pbrMetallicRoughness: {
          baseColorFactor: color,
          metallicFactor: 0.25,
          roughnessFactor: 0.65,
        },
      },
    ],
    buffers: [
      {
        uri:
          "data:application/octet-stream;base64," + buffer.toString("base64"),
        byteLength: buffer.length,
      },
    ],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: p.byteLength, target: 34962 },
      {
        buffer: 0,
        byteOffset: p.byteLength,
        byteLength: n.byteLength,
        target: 34962,
      },
    ],
    accessors: [
      {
        bufferView: 0,
        componentType: 5126,
        count: positions.length / 3,
        type: "VEC3",
        min,
        max,
      },
      {
        bufferView: 1,
        componentType: 5126,
        count: normals.length / 3,
        type: "VEC3",
      },
    ],
  };
  writeFileSync("public/models/" + name + ".gltf", JSON.stringify(gltf));
}
mkdirSync("public/models", { recursive: true });
model(
  "aircraft",
  [
    [0, 0, 0, 30, 2.5, 2.5],
    [-2, 0, 0, 5, 1, 27],
    [-11, 1.5, 0, 5, 5, 1],
    [-11, 0, 0, 4, 1, 10],
  ],
  [0.65, 0.86, 0.9, 1],
);
model(
  "vessel",
  [
    [0, 0, 0, 30, 3, 8],
    [-5, 3, 0, 9, 5, 6],
    [6, 2, 0, 6, 2, 5],
  ],
  [0.62, 0.75, 0.88, 1],
);
model(
  "satellite",
  [
    [0, 0, 0, 3, 3, 3],
    [0, 0, 5, 4, 0.2, 6],
    [0, 0, -5, 4, 0.2, 6],
  ],
  [0.72, 0.65, 0.91, 1],
);
