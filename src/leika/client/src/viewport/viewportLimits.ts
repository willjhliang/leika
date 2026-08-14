import { commonRendererStringWithinLimit, utf8ByteLength } from "../guiLimits";
import { matplotlibSvgSourceError } from "../rendererSourceLimits";
import { PLOTLY_JSON_MAX_SERIALIZED_CHARACTERS } from "./plotlyPayload";
import type { ViewportContentPane } from "./ViewportState";

/** Retained pane roots stay mounted even while hidden/minimized. */
export const MAX_LIVE_VIEWPORT_CONTENT_PANES = 128;
export const MAX_LIVE_VIEWPORT_VISER_PANES = 16;
export const MAX_VIEWPORT_SOURCE_CODE_UNITS = 32 * 1024 * 1024;
export const MAX_VIEWPORT_RETAINED_BYTES = 256 * 1024 * 1024;
export const MAX_VIEWPORT_URL_CODE_UNITS = 16_384;

export interface ViewportSourceCost {
  retainedBytes: number;
  textCodeUnits: number;
}

export function viewportSourceCostWithinLimits(
  cost: ViewportSourceCost,
): boolean {
  return (
    cost.retainedBytes <= MAX_VIEWPORT_RETAINED_BYTES &&
    cost.textCodeUnits <= MAX_VIEWPORT_SOURCE_CODE_UNITS
  );
}

export function viewportPaneSourceCost(
  pane: ViewportContentPane,
): ViewportSourceCost {
  let retainedBytes = 0;
  let textCodeUnits = 0;
  for (const value of Object.values(pane.props)) {
    if (typeof value === "string") {
      textCodeUnits += value.length;
      retainedBytes += utf8ByteLength(value);
    } else if (ArrayBuffer.isView(value)) {
      retainedBytes += value.byteLength;
    }
  }
  return { retainedBytes, textCodeUnits };
}

export function viewportPaneWithinEntityLimits(
  pane: ViewportContentPane,
): boolean {
  if (!commonRendererStringWithinLimit(pane.props.title)) return false;
  if (pane.kind === "matplotlib") {
    return matplotlibSvgSourceError(pane.props._svg) === null;
  }
  if (pane.kind === "plotly") {
    return (
      pane.props._plotly_json_str.length <=
        PLOTLY_JSON_MAX_SERIALIZED_CHARACTERS &&
      pane.props._theme_templates.length <=
        PLOTLY_JSON_MAX_SERIALIZED_CHARACTERS
    );
  }
  if (pane.kind === "viser" && pane.props._url !== null) {
    return pane.props._url.length <= MAX_VIEWPORT_URL_CODE_UNITS;
  }
  return true;
}

export function viewportPanesWithinAggregateLimits(
  panes: Iterable<ViewportContentPane>,
): boolean {
  let count = 0;
  let viserCount = 0;
  let retainedBytes = 0;
  let textCodeUnits = 0;
  for (const pane of panes) {
    count += 1;
    if (count > MAX_LIVE_VIEWPORT_CONTENT_PANES) return false;
    if (pane.kind === "viser") {
      viserCount += 1;
      if (viserCount > MAX_LIVE_VIEWPORT_VISER_PANES) return false;
    }
    if (!viewportPaneWithinEntityLimits(pane)) return false;
    const cost = viewportPaneSourceCost(pane);
    retainedBytes += cost.retainedBytes;
    textCodeUnits += cost.textCodeUnits;
    if (!viewportSourceCostWithinLimits({ retainedBytes, textCodeUnits }))
      return false;
  }
  return true;
}
