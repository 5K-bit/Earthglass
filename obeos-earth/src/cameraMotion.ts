/** Ignore floating-point camera drift while retaining deliberate motion and slow accumulated movement. */
export class CameraMotion {
  private position?: readonly number[];
  private direction?: readonly number[];
  private changedAt = -Infinity;
  sample(position: readonly number[], direction: readonly number[], height: number, now: number): boolean {
    if (!this.position || !this.direction) {
      this.position = [...position];
      this.direction = [...direction];
      return false;
    }
    const distanceSquared = (a: readonly number[], b: readonly number[]) =>
      a.reduce((sum, value, index) => sum + (value - b[index]) ** 2, 0);
    const tolerance = Math.max(0.05, Math.abs(height) * 1e-7);
    if (distanceSquared(position, this.position) > tolerance ** 2 ||
        distanceSquared(direction, this.direction) > 1e-14) {
      this.position = [...position];
      this.direction = [...direction];
      this.changedAt = now;
    }
    return now - this.changedAt < 350;
  }
}
