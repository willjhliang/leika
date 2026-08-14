import type { MediaSize } from "./components/mediaPreviewSize";

/** A page-wide upper bound on simultaneously mounted direct raster decoders.
 * Each rendered copy owns pixels independently because browser decode sharing
 * is implementation-dependent. */
export const MAX_MOUNTED_RASTER_PIXELS = 128 * 1024 * 1024;

export interface RasterPixelLease {
  readonly active: boolean;
  readonly pixels: number;
  release(): void;
}

const rasterLeaseBudget = Symbol("raster lease budget");
type OwnedRasterPixelLease = RasterPixelLease & {
  readonly [rasterLeaseBudget]: RasterPixelBudget;
  deactivate(): void;
};

export class RasterPixelBudget {
  private usedPixelsValue = 0;
  private generationValue = 0;
  private epochValue = 0;
  private readonly listeners = new Set<() => void>();

  constructor(private readonly maxPixels = MAX_MOUNTED_RASTER_PIXELS) {}

  get usedPixels(): number {
    return this.usedPixelsValue;
  }

  /** Monotonic capacity-change snapshot for denied-owner subscriptions. */
  get generation(): number {
    return this.generationValue;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private capacityChanged(): void {
    this.generationValue += 1;
    for (const listener of this.listeners) listener();
  }

  private pixelsFor(size: MediaSize): number | null {
    const pixels = size.width * size.height;
    return Number.isSafeInteger(pixels) && pixels > 0 ? pixels : null;
  }

  private makeLease(pixels: number): OwnedRasterPixelLease {
    const epoch = this.epochValue;
    const epochIsCurrent = () => this.epochValue === epoch;
    let active = true;
    const lease: OwnedRasterPixelLease = {
      [rasterLeaseBudget]: this,
      get active() {
        return active && epochIsCurrent();
      },
      pixels,
      deactivate: () => {
        active = false;
      },
      release: () => {
        if (!lease.active) {
          active = false;
          return;
        }
        active = false;
        this.usedPixelsValue -= pixels;
        if (this.usedPixelsValue < 0) {
          throw new Error("raster pixel budget accounting underflow");
        }
        this.capacityChanged();
      },
    };
    return lease;
  }

  reserve(size: MediaSize): RasterPixelLease | null {
    return this.replace(null, size);
  }

  /** Atomically transfer one mounted owner's reservation to a new source.
   * Growth is admitted against the old owner's pixels before invalidating its
   * lease, so replacements neither create an accounting gap nor spuriously
   * fail merely because their own previous source occupies the budget. */
  replace(
    previous: RasterPixelLease | null,
    size: MediaSize,
  ): RasterPixelLease | null {
    const pixels = this.pixelsFor(size);
    if (pixels === null || pixels > this.maxPixels) return null;
    const owned = previous as OwnedRasterPixelLease | null;
    const replaceable =
      owned !== null && owned[rasterLeaseBudget] === this && owned.active;
    const previousPixels = replaceable ? owned.pixels : 0;
    if (pixels > this.maxPixels - this.usedPixelsValue + previousPixels) {
      return null;
    }

    this.usedPixelsValue += pixels - previousPixels;
    if (replaceable) owned.deactivate();
    const lease = this.makeLease(pixels);
    if (pixels < previousPixels) this.capacityChanged();
    return lease;
  }

  /** Invalidate every lease when connection-owned renderer state is reset. */
  reset(): void {
    this.usedPixelsValue = 0;
    this.epochValue += 1;
    this.capacityChanged();
  }

  resetForTests(): void {
    this.reset();
  }
}

export const mountedRasterPixels = new RasterPixelBudget();

export function resetMountedRasterPixels(): void {
  mountedRasterPixels.reset();
}
