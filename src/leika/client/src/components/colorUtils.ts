// Utility functions for color conversions.

export type RgbTuple = [number, number, number];
export type RgbaTuple = [number, number, number, number]; // R, G, B in [0, 255], A in [0, 255].
export type HsvColor = { h: number; s: number; v: number };

// Convert RGB tuple to rgb() string.
// Input: RGB values in [0, 255].
export function rgbToString(rgb: RgbTuple): string {
  return `rgb(${Math.round(rgb[0])}, ${Math.round(rgb[1])}, ${Math.round(
    rgb[2],
  )})`;
}

// Convert RGBA tuple to rgba() string.
// Input: RGB values in [0, 255], A in [0, 255].
// Output: CSS rgba() string with alpha in [0, 1].
export function rgbaToString(rgba: RgbaTuple): string {
  return `rgba(${Math.round(rgba[0])}, ${Math.round(rgba[1])}, ${Math.round(
    rgba[2],
  )}, ${(rgba[3] / 255).toFixed(4)})`;
}

function rgbChannels(match: RegExpMatchArray): RgbTuple | null {
  const channels = [match[1], match[2], match[3]].map(Number) as RgbTuple;
  return channels.every((channel) => channel >= 0 && channel <= 255)
    ? channels
    : null;
}

// Parse any string to RGB tuple.
// Output: RGB values in [0, 255].
export function parseToRgb(value: string): RgbTuple | null {
  // Try to parse rgb(r, g, b) format.
  const rgbMatch = value
    .trim()
    .match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/i);
  if (rgbMatch) {
    return rgbChannels(rgbMatch);
  }

  // Try to parse hex format (#RGB or #RRGGBB).
  const hexMatch = value.trim().match(/^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$/);
  if (hexMatch) {
    const hex = hexMatch[1];
    if (hex.length === 3) {
      return [
        Number.parseInt(hex[0] + hex[0], 16),
        Number.parseInt(hex[1] + hex[1], 16),
        Number.parseInt(hex[2] + hex[2], 16),
      ];
    }
    return [1, 3, 5].map((index) =>
      Number.parseInt(hex.slice(index - 1, index + 1), 16),
    ) as RgbTuple;
  }

  return null;
}

// Parse any string to RGBA tuple.
// Output: RGB values in [0, 255], A in [0, 255].
export function parseToRgba(value: string): RgbaTuple | null {
  // Try to parse CSS `rgba(r, g, b, a)` format.
  const rgbaMatch = value
    .trim()
    .match(
      /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*((?:\d+(?:\.\d*)?|\.\d+))\s*\)$/i,
    );
  if (rgbaMatch) {
    const channels = rgbChannels(rgbaMatch);
    const alpha = Number.parseFloat(rgbaMatch[4]);
    return channels === null || alpha < 0 || alpha > 1
      ? null
      : [...channels, Math.round(alpha * 255)];
  }

  // Try to parse hex format (#RGB, #RGBA, #RRGGBB, or #RRGGBBAA).
  const hexMatch = value
    .trim()
    .match(/^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$/);
  if (hexMatch) {
    const hex = hexMatch[1];
    if (hex.length === 4) {
      // Convert #RGBA to full RGBA values.
      return [
        parseInt(hex[0] + hex[0], 16),
        parseInt(hex[1] + hex[1], 16),
        parseInt(hex[2] + hex[2], 16),
        parseInt(hex[3] + hex[3], 16),
      ];
    } else if (hex.length === 8) {
      // Parse #RRGGBBAA format.
      return [
        parseInt(hex.substring(0, 2), 16),
        parseInt(hex.substring(2, 4), 16),
        parseInt(hex.substring(4, 6), 16),
        parseInt(hex.substring(6, 8), 16),
      ];
    }
  }

  // Try to parse RGB format and add default alpha.
  const rgbResult = parseToRgb(value);
  if (rgbResult) {
    return [...rgbResult, 255];
  }

  return null;
}

/** Convert any accepted RGB(A) text value into a native color-input value. */
export function colorValueToHex(value: string): string {
  const rgba = parseToRgba(value);
  if (rgba === null) return "#000000";
  return `#${rgba
    .slice(0, 3)
    .map((channel) =>
      Math.max(0, Math.min(255, Math.round(channel)))
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;
}

/** Preserve the normalized alpha channel when a native color input changes RGB. */
export function colorAlpha(value: string): string {
  const rgba = parseToRgba(value);
  if (rgba === null) return "1";
  return (Math.max(0, Math.min(255, rgba[3])) / 255).toFixed(4);
}

/** Change opacity while preserving the current RGB channels. */
export function colorWithOpacity(
  currentValue: string,
  opacity: number,
): string {
  const rgba = parseToRgba(currentValue) ?? [0, 0, 0, 255];
  const currentOpacity = rgba[3] / 255;
  const normalized = Number.isFinite(opacity)
    ? Math.max(0, Math.min(1, opacity))
    : currentOpacity;
  return `rgba(${rgba[0]}, ${rgba[1]}, ${rgba[2]}, ${normalized.toFixed(4)})`;
}

/** Combine a native color-input value with Leika's RGB(A) text format. */
export function colorFromHex(
  hex: string,
  format: "rgb" | "rgba",
  currentValue: string,
): string {
  const channels = [1, 3, 5].map((index) =>
    Number.parseInt(hex.slice(index, index + 2), 16),
  ) as RgbTuple;
  return colorFromRgb(channels, format, currentValue);
}

/** Combine RGB channels with Leika's RGB(A) text format. */
export function colorFromRgb(
  rgb: RgbTuple,
  format: "rgb" | "rgba",
  currentValue: string,
): string {
  const channels = rgb.map((channel) =>
    Math.max(0, Math.min(255, Math.round(channel))),
  ) as RgbTuple;
  return format === "rgba"
    ? `rgba(${channels.join(", ")}, ${colorAlpha(currentValue)})`
    : `rgb(${channels.join(", ")})`;
}

/** Convert RGB channels into hue, saturation, and value percentages. */
export function rgbToHsv(rgb: RgbTuple): HsvColor {
  const [red, green, blue] = rgb.map(
    (channel) => Math.max(0, Math.min(255, channel)) / 255,
  ) as RgbTuple;
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const delta = max - min;
  let hue = 0;

  if (delta !== 0) {
    if (max === red) hue = 60 * (((green - blue) / delta) % 6);
    else if (max === green) hue = 60 * ((blue - red) / delta + 2);
    else hue = 60 * ((red - green) / delta + 4);
  }

  return {
    h: (hue + 360) % 360,
    s: max === 0 ? 0 : (delta / max) * 100,
    v: max * 100,
  };
}

/** Convert hue, saturation, and value percentages into RGB channels. */
export function hsvToRgb({ h, s, v }: HsvColor): RgbTuple {
  const hue = ((h % 360) + 360) % 360;
  const saturation = Math.max(0, Math.min(100, s)) / 100;
  const value = Math.max(0, Math.min(100, v)) / 100;
  const chroma = value * saturation;
  const secondary = chroma * (1 - Math.abs(((hue / 60) % 2) - 1));
  const offset = value - chroma;
  const sector =
    hue < 60
      ? [chroma, secondary, 0]
      : hue < 120
        ? [secondary, chroma, 0]
        : hue < 180
          ? [0, chroma, secondary]
          : hue < 240
            ? [0, secondary, chroma]
            : hue < 300
              ? [secondary, 0, chroma]
              : [chroma, 0, secondary];
  return sector.map((channel) =>
    Math.round((channel + offset) * 255),
  ) as RgbTuple;
}

/** Convert RGB channels into hue, saturation, and lightness percentages. */
export function rgbToHsl(rgb: RgbTuple): [number, number, number] {
  const [red, green, blue] = rgb.map(
    (channel) => Math.max(0, Math.min(255, channel)) / 255,
  ) as RgbTuple;
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const delta = max - min;
  const lightness = (max + min) / 2;
  let hue = 0;

  if (delta !== 0) {
    if (max === red) hue = 60 * (((green - blue) / delta) % 6);
    else if (max === green) hue = 60 * ((blue - red) / delta + 2);
    else hue = 60 * ((red - green) / delta + 4);
  }

  const saturation =
    delta === 0 ? 0 : delta / (1 - Math.abs(2 * lightness - 1));
  return [(hue + 360) % 360, saturation * 100, lightness * 100];
}

/** Convert hue, saturation, and lightness percentages into RGB channels. */
export function hslToRgb(hsl: [number, number, number]): RgbTuple {
  const hue = ((hsl[0] % 360) + 360) % 360;
  const saturation = Math.max(0, Math.min(100, hsl[1])) / 100;
  const lightness = Math.max(0, Math.min(100, hsl[2])) / 100;
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const secondary = chroma * (1 - Math.abs(((hue / 60) % 2) - 1));
  const offset = lightness - chroma / 2;
  const sector =
    hue < 60
      ? [chroma, secondary, 0]
      : hue < 120
        ? [secondary, chroma, 0]
        : hue < 180
          ? [0, chroma, secondary]
          : hue < 240
            ? [0, secondary, chroma]
            : hue < 300
              ? [secondary, 0, chroma]
              : [chroma, 0, secondary];
  return sector.map((channel) =>
    Math.round((channel + offset) * 255),
  ) as RgbTuple;
}

/** WCAG relative luminance of RGB channels, in [0, 1]. */
export function relativeLuminance(rgb: RgbTuple): number {
  const [red, green, blue] = rgb.map((channel) => {
    const normalized = Math.max(0, Math.min(255, channel)) / 255;
    return normalized <= 0.03928
      ? normalized / 12.92
      : Math.pow((normalized + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** The two neutrals `--primary-foreground` takes in `index.css`: the light
 * theme prints near-white on its near-black accent, and the dark theme prints
 * near-black on its near-white one. */
const LIGHT_ON_ACCENT = "oklch(0.985 0 0)";
const DARK_ON_ACCENT = "oklch(0.205 0 0)";

/** Luminance above which an accent is pale enough to print dark text on.
 *
 * Pure contrast crosses over at 0.179, where white and black score equally.
 * Picking the winner there flips to dark text on saturated mid-tones -- a
 * strong blue or orange -- which every convention prints white on, and which
 * looks like a bug rather than a choice. This sits well above the crossover so
 * only genuinely light accents take dark text. Between 0.179 and here, white
 * gives up some contrast: still past the 3:1 that WCAG asks of a UI component
 * or large text, but short of the 4.5:1 for body copy. Nothing typed at body
 * size uses this pair -- it fills checkboxes, slider ranges, and buttons. */
const DARK_TEXT_ABOVE = 0.4;

/** Pick the readable `--primary-foreground` for an accent color.
 *
 * The stock foregrounds assume an accent at one end of the lightness range, so
 * a user-chosen mid-tone or pale accent would otherwise print near-white text
 * on a near-white fill. */
export function accentForeground(accent: string): string {
  const rgb = parseToRgb(accent);
  if (rgb === null) return LIGHT_ON_ACCENT;
  return relativeLuminance(rgb) > DARK_TEXT_ABOVE
    ? DARK_ON_ACCENT
    : LIGHT_ON_ACCENT;
}

// Check if two RGB tuples are equal.
// Input: RGB values in [0, 255].
export function rgbEqual(a: RgbTuple, b: RgbTuple): boolean {
  return a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
}

// Check if two RGBA tuples are equal.
// Input: RGB values in [0, 255], A in [0, 255].
export function rgbaEqual(a: RgbaTuple, b: RgbaTuple): boolean {
  return a[0] === b[0] && a[1] === b[1] && a[2] === b[2] && a[3] === b[3];
}
