import type {
  GuiComponentMessage,
  GuiModalMessage,
  GuiTabMessage,
  GuiTabUpdateMessage,
  NotificationShowMessage,
  RegisterCommandMessage,
} from "./WebsocketMessages";
import { guiHtmlSourceError } from "./rendererSourceLimits";
import { validFileTransferMimeType } from "./fileTransferValidation";
import { PLOTLY_JSON_MAX_SERIALIZED_CHARACTERS } from "./viewport/plotlyPayload";

/** One browser receives both the server-global and client-local GUI scopes. */
export const MAX_BROWSER_LIVE_GUI_COMPONENTS = 8_192;
export const MAX_BROWSER_LIVE_GUI_COMMANDS = 2_048;
export const MAX_BROWSER_LIVE_GUI_MODALS = 64;
export const MAX_BROWSER_LIVE_GUI_TABS = 32_768;
export const MAX_BROWSER_LIVE_NOTIFICATIONS = 256;

/** Per-entity collection and string limits mirrored by each Python GuiApi. */
export const MAX_GUI_COLLECTION_ITEMS = 4_096;
export const MAX_GUI_COLLECTION_ITEM_CODE_UNITS = 16_384;
export const MAX_GUI_COMMON_STRING_CODE_UNITS = 16_384;
export const MAX_GUI_TEXT_VALUE_CODE_UNITS = 1_048_576;
export const MAX_GUI_MARKDOWN_SOURCE_BYTES = 1 * 1024 * 1024;
export const MAX_GUI_BUTTON_HOLD_FREQUENCIES = 64;
export const MAX_GUI_BUTTON_HOLD_FREQUENCY_HZ = 60;
export const MAX_NOTIFICATION_AUTO_CLOSE_MILLISECONDS = 2_147_483_647;
export const MAX_NOTIFICATION_AUTO_CLOSE_SECONDS =
  MAX_NOTIFICATION_AUTO_CLOSE_MILLISECONDS / 1_000;
/** Sum of the two independently valid Python GUI scopes visible to one tab. */
export const MAX_BROWSER_GUI_COLLECTION_ITEMS = 32_768;
export const MAX_BROWSER_GUI_TEXT_CODE_UNITS = 32 * 1024 * 1024;
export const MAX_BROWSER_GUI_RETAINED_BYTES = 256 * 1024 * 1024;

export interface GuiConfigCost {
  collectionItems: number;
  retainedBytes: number;
  textCodeUnits: number;
}

/** Count UTF-8 bytes without allocating an encoded copy of a large string. */
export function utf8ByteLength(value: string): number {
  let bytes = 0;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code <= 0x7f) bytes += 1;
    else if (code <= 0x7ff) bytes += 2;
    else if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        bytes += 4;
        index += 1;
      } else {
        // TextEncoder replaces an unpaired surrogate with U+FFFD.
        bytes += 3;
      }
    } else {
      bytes += 3;
    }
  }
  return bytes;
}

/** Cost the retained, user-controlled state payload (value + props).
 *
 * Arrays count every element. Strings count both JavaScript UTF-16 code units
 * and their UTF-8 source bytes; binary views count their owned byte length.
 * Object field names are generated schema, not user state, and are excluded.
 */
export function guiConfigCost(config: GuiComponentMessage): GuiConfigCost {
  const pending: unknown[] = [config.props];
  const visited = new WeakSet<object>();
  const maxNodes = 500_000;
  let nodes = 0;
  if ("value" in config) pending.push(config.value);
  let collectionItems = 0;
  let retainedBytes = 0;
  let textCodeUnits = 0;
  while (pending.length > 0) {
    nodes += 1;
    if (nodes > maxNodes) {
      return {
        collectionItems: Number.POSITIVE_INFINITY,
        retainedBytes: Number.POSITIVE_INFINITY,
        textCodeUnits: Number.POSITIVE_INFINITY,
      };
    }
    const value = pending.pop();
    if (typeof value === "string") {
      textCodeUnits += value.length;
      retainedBytes += utf8ByteLength(value);
      continue;
    }
    if (ArrayBuffer.isView(value)) {
      retainedBytes += value.byteLength;
      continue;
    }
    if (value instanceof ArrayBuffer) {
      retainedBytes += value.byteLength;
      continue;
    }
    if (Array.isArray(value)) {
      collectionItems += value.length;
      for (const item of value) pending.push(item);
      continue;
    }
    if (typeof value === "object" && value !== null) {
      if (visited.has(value)) {
        return {
          collectionItems: Number.POSITIVE_INFINITY,
          retainedBytes: Number.POSITIVE_INFINITY,
          textCodeUnits: Number.POSITIVE_INFINITY,
        };
      }
      visited.add(value);
      for (const item of Object.values(value)) pending.push(item);
    }
  }
  return { collectionItems, retainedBytes, textCodeUnits };
}

export function addGuiConfigCosts(
  left: GuiConfigCost,
  right: GuiConfigCost,
): GuiConfigCost {
  return {
    collectionItems: left.collectionItems + right.collectionItems,
    retainedBytes: left.retainedBytes + right.retainedBytes,
    textCodeUnits: left.textCodeUnits + right.textCodeUnits,
  };
}

export function subtractGuiConfigCosts(
  left: GuiConfigCost,
  right: GuiConfigCost,
): GuiConfigCost {
  return {
    collectionItems: left.collectionItems - right.collectionItems,
    retainedBytes: left.retainedBytes - right.retainedBytes,
    textCodeUnits: left.textCodeUnits - right.textCodeUnits,
  };
}

export function guiConfigCostWithinBrowserLimits(cost: GuiConfigCost): boolean {
  return (
    cost.collectionItems <= MAX_BROWSER_GUI_COLLECTION_ITEMS &&
    cost.retainedBytes <= MAX_BROWSER_GUI_RETAINED_BYTES &&
    cost.textCodeUnits <= MAX_BROWSER_GUI_TEXT_CODE_UNITS
  );
}

export function commonRendererStringWithinLimit(
  value: string | null | undefined,
): boolean {
  return (
    value === null ||
    value === undefined ||
    value.length <= MAX_GUI_COMMON_STRING_CODE_UNITS
  );
}

function commonRendererStringsWithinLimits(
  config: GuiComponentMessage,
): boolean {
  const props = config.props as Record<string, unknown>;
  for (const key of ["label", "hint", "text", "_icon_html"] as const) {
    const value = props[key];
    if (typeof value === "string" && !commonRendererStringWithinLimit(value))
      return false;
  }
  if (
    (config.type === "GuiSliderMessage" ||
      config.type === "GuiMultiSliderMessage") &&
    config.props._marks !== null
  ) {
    for (const mark of config.props._marks) {
      if (!commonRendererStringWithinLimit(mark.label)) return false;
    }
  }
  return true;
}

function boundedCollectionStrings(values: readonly string[]): boolean {
  if (values.length > MAX_GUI_COLLECTION_ITEMS) return false;
  for (const value of values) {
    if (value.length > MAX_GUI_COLLECTION_ITEM_CODE_UNITS) return false;
  }
  return true;
}

export function holdCallbackFrequenciesWithinLimits(
  frequencies: readonly number[],
): boolean {
  if (frequencies.length > MAX_GUI_BUTTON_HOLD_FREQUENCIES) return false;
  const unique = new Set<number>();
  for (const frequency of frequencies) {
    if (
      !Number.isFinite(frequency) ||
      frequency <= 0 ||
      frequency > MAX_GUI_BUTTON_HOLD_FREQUENCY_HZ ||
      unique.has(frequency)
    ) {
      return false;
    }
    unique.add(frequency);
  }
  return true;
}

/** Defense in depth for directly rendered/test-created button configs. */
export function boundedHoldCallbackFrequencies(
  frequencies: readonly number[],
): number[] {
  const bounded: number[] = [];
  const unique = new Set<number>();
  for (const frequency of frequencies) {
    if (
      bounded.length >= MAX_GUI_BUTTON_HOLD_FREQUENCIES ||
      !Number.isFinite(frequency) ||
      frequency <= 0 ||
      frequency > MAX_GUI_BUTTON_HOLD_FREQUENCY_HZ ||
      unique.has(frequency)
    ) {
      continue;
    }
    unique.add(frequency);
    bounded.push(frequency);
  }
  return bounded;
}

/** Reject retained/rendered GUI shapes that exceed the public server limits.
 *
 * This is deliberately independent of the generated structural validator:
 * the protocol can describe larger generic tuples, while the live GUI cannot
 * safely retain or render tens of thousands of rows from one component.
 */
export function guiConfigWithinEntityLimits(
  config: GuiComponentMessage,
): boolean {
  if (!commonRendererStringsWithinLimits(config)) return false;
  switch (config.type) {
    case "GuiHtmlMessage":
      return guiHtmlSourceError(config.props.content) === null;
    case "GuiPlotlyMessage":
      return (
        config.props._plotly_json_str.length <=
        PLOTLY_JSON_MAX_SERIALIZED_CHARACTERS
      );
    case "GuiUploadButtonMessage":
      return validFileTransferMimeType(config.props.mime_type);
    case "GuiTextMessage":
      return (
        config.value.length <= MAX_GUI_TEXT_VALUE_CODE_UNITS &&
        utf8ByteLength(config.props._source) <= MAX_GUI_MARKDOWN_SOURCE_BYTES
      );
    case "GuiListMessage":
      return boundedCollectionStrings(config.value);
    case "GuiChecklistMessage":
      if (config.value.length > MAX_GUI_COLLECTION_ITEMS) return false;
      for (const [text] of config.value) {
        if (text.length > MAX_GUI_COLLECTION_ITEM_CODE_UNITS) return false;
      }
      return true;
    case "GuiDropdownMessage":
      return (
        commonRendererStringWithinLimit(config.value) &&
        boundedCollectionStrings(config.props.options)
      );
    case "GuiButtonGroupMessage":
      return (
        commonRendererStringWithinLimit(config.value) &&
        boundedCollectionStrings(config.props.options) &&
        config.props.color.length <= MAX_GUI_COLLECTION_ITEMS &&
        config.props._merge.length <= MAX_GUI_COLLECTION_ITEMS
      );
    case "GuiToggleGroupMessage":
      return (
        boundedCollectionStrings(config.props.options) &&
        boundedCollectionStrings(config.value) &&
        config.props.color.length <= MAX_GUI_COLLECTION_ITEMS &&
        config.props._merge.length <= MAX_GUI_COLLECTION_ITEMS
      );
    case "GuiTabGroupMessage":
      if (config.props._tabs.length > MAX_GUI_COLLECTION_ITEMS) return false;
      for (const tab of config.props._tabs) {
        if (
          tab.label.length > MAX_GUI_COLLECTION_ITEM_CODE_UNITS ||
          !commonRendererStringWithinLimit(tab.icon_html)
        )
          return false;
      }
      return true;
    case "GuiSliderMessage":
      return (
        config.props._marks === null ||
        config.props._marks.length <= MAX_GUI_COLLECTION_ITEMS
      );
    case "GuiMultiSliderMessage":
      return (
        config.value.length <= MAX_GUI_COLLECTION_ITEMS &&
        (config.props._marks === null ||
          config.props._marks.length <= MAX_GUI_COLLECTION_ITEMS)
      );
    case "GuiButtonMessage":
      return holdCallbackFrequenciesWithinLimits(
        config.props._hold_callback_freqs,
      );
    default:
      return true;
  }
}

export function guiModalWithinEntityLimits(config: GuiModalMessage): boolean {
  return commonRendererStringWithinLimit(config.title);
}

export function guiTabWithinEntityLimits(
  config: GuiTabMessage | GuiTabUpdateMessage,
): boolean {
  return (
    config.label.length <= MAX_GUI_COLLECTION_ITEM_CODE_UNITS &&
    commonRendererStringWithinLimit(config.icon_html)
  );
}

export function guiCommandWithinEntityLimits(
  config: RegisterCommandMessage,
): boolean {
  return (
    commonRendererStringWithinLimit(config.props.label) &&
    commonRendererStringWithinLimit(config.props.description) &&
    commonRendererStringWithinLimit(config.props._icon_html)
  );
}

export function notificationWithinEntityLimits(
  props: NotificationShowMessage["props"],
): boolean {
  const seconds = props.auto_close_seconds;
  return (
    commonRendererStringWithinLimit(props.title) &&
    commonRendererStringWithinLimit(props.body) &&
    (seconds === null ||
      (Number.isFinite(seconds) &&
        seconds >= 0 &&
        seconds <= MAX_NOTIFICATION_AUTO_CLOSE_SECONDS))
  );
}

export function guiStringsCost(
  values: readonly (string | null | undefined)[],
): GuiConfigCost {
  let retainedBytes = 0;
  let textCodeUnits = 0;
  for (const value of values) {
    if (value === null || value === undefined) continue;
    retainedBytes += utf8ByteLength(value);
    textCodeUnits += value.length;
  }
  return { collectionItems: 0, retainedBytes, textCodeUnits };
}

export function guiModalCost(config: GuiModalMessage): GuiConfigCost {
  return guiStringsCost([config.title]);
}

export function guiCommandCost(config: RegisterCommandMessage): GuiConfigCost {
  return guiStringsCost([
    config.props.label,
    config.props.description,
    config.props._icon_html,
  ]);
}
