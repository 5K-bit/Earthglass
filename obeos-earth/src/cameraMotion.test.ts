import { expect, it } from "vitest";
import { CameraMotion } from "./cameraMotion";
it("keeps numerical drift idle and settles after actual camera movement", () => {
  const motion = new CameraMotion(), p = [6378000, 0, 0], d = [-1, 0, 0];
  expect(motion.sample(p, d, 5000, 0)).toBe(false);
  for(let i=1;i<100;i++) expect(motion.sample([p[0]+i*1e-9,0,0],d,5000,i*33)).toBe(false);
  expect(motion.sample([p[0]+1,0,0],d,5000,3400)).toBe(true);
  expect(motion.sample([p[0]+1,0,0],d,5000,3600)).toBe(true);
  expect(motion.sample([p[0]+1,0,0],d,5000,3800)).toBe(false);
});
it("detects accumulated slow movement and direction changes", () => {
  const motion = new CameraMotion(), d=[-1,0,0];
  motion.sample([0,0,0],d,1000,0);
  for(let i=1;i<5;i++) expect(motion.sample([i*.01,0,0],d,1000,i*30)).toBe(false);
  expect(motion.sample([.06,0,0],d,1000,180)).toBe(true);
  expect(motion.sample([.06,0,0],d,1000,600)).toBe(false);
  expect(motion.sample([.06,0,0],[-1,0.001,0],1000,700)).toBe(true);
});
