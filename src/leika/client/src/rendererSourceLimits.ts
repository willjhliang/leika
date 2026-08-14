export const GUI_HTML_MAX_SOURCE_CODE_UNITS = 1 * 1024 * 1024;
export const MATPLOTLIB_SVG_MAX_SOURCE_CODE_UNITS = 16 * 1024 * 1024;

/** Validate source before handing it to a browser parser. These limits count
 * JavaScript UTF-16 code units (`string.length`), which makes the boundary
 * allocation-free and gives Python a precise wire-compatible contract. */
export function guiHtmlSourceError(source: unknown): string | null {
  if (typeof source !== "string") return "HTML content is invalid.";
  if (source.length > GUI_HTML_MAX_SOURCE_CODE_UNITS) {
    return "HTML content exceeds the 1 Mi-character browser render limit.";
  }
  return null;
}

export function matplotlibSvgSourceError(source: unknown): string | null {
  if (typeof source !== "string") return "Matplotlib figure is invalid.";
  if (source.length > MATPLOTLIB_SVG_MAX_SOURCE_CODE_UNITS) {
    return "Matplotlib figure exceeds the 16 Mi-character browser render limit.";
  }
  return null;
}
