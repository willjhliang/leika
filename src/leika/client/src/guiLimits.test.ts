import { describe, expect, it } from "vitest";

import {
  MAX_BROWSER_GUI_COLLECTION_ITEMS,
  MAX_BROWSER_GUI_RETAINED_BYTES,
  MAX_BROWSER_GUI_TEXT_CODE_UNITS,
  MAX_GUI_COLLECTION_ITEMS,
  MAX_GUI_COLLECTION_ITEM_CODE_UNITS,
  MAX_GUI_BUTTON_HOLD_FREQUENCIES,
  MAX_GUI_BUTTON_HOLD_FREQUENCY_HZ,
  MAX_GUI_MARKDOWN_SOURCE_BYTES,
  boundedHoldCallbackFrequencies,
  guiConfigCost,
  guiConfigCostWithinBrowserLimits,
  guiConfigWithinEntityLimits,
  utf8ByteLength,
} from "./guiLimits";
import type {
  GuiDropdownMessage,
  GuiFolderMessage,
  GuiButtonMessage,
  GuiHtmlMessage,
  GuiImageMessage,
  GuiPlotlyMessage,
  GuiRadioListMessage,
  GuiTextMessage,
  GuiUploadButtonMessage,
} from "./WebsocketMessages";
import { GUI_HTML_MAX_SOURCE_CODE_UNITS } from "./rendererSourceLimits";
import { PLOTLY_JSON_MAX_SERIALIZED_CHARACTERS } from "./viewport/plotlyPayload";

const folder = (): GuiFolderMessage => ({
  type: "GuiFolderMessage",
  uuid: "folder",
  container_uuid: "root",
  props: {
    order: 0,
    label: "Label",
    visible: true,
    expand_by_default: false,
  },
});

describe("GUI retained-cost admission", () => {
  it("counts UTF-16 units, exact UTF-8 bytes, and binary image bytes", () => {
    const image: GuiImageMessage = {
      type: "GuiImageMessage",
      uuid: "image",
      container_uuid: "root",
      props: {
        order: 0,
        label: "A😀",
        _data: new Uint8Array(17),
        _format: "png",
        visible: true,
      },
    };

    expect(guiConfigCost(image)).toEqual({
      collectionItems: 0,
      retainedBytes: 25,
      textCodeUnits: 6,
    });
    expect(utf8ByteLength("A😀")).toBe(5);
    expect(utf8ByteLength("\ud800")).toBe(3);
  });

  it("fails closed on cyclic direct-call objects instead of looping", () => {
    const config = folder();
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;
    (config as unknown as { props: Record<string, unknown> }).props = cyclic;

    expect(guiConfigCost(config)).toEqual({
      collectionItems: Number.POSITIVE_INFINITY,
      retainedBytes: Number.POSITIVE_INFINITY,
      textCodeUnits: Number.POSITIVE_INFINITY,
    });
  });

  it("admits exact aggregate boundaries and rejects each +1", () => {
    expect(
      guiConfigCostWithinBrowserLimits({
        collectionItems: MAX_BROWSER_GUI_COLLECTION_ITEMS,
        retainedBytes: MAX_BROWSER_GUI_RETAINED_BYTES,
        textCodeUnits: MAX_BROWSER_GUI_TEXT_CODE_UNITS,
      }),
    ).toBe(true);
    expect(
      guiConfigCostWithinBrowserLimits({
        collectionItems: MAX_BROWSER_GUI_COLLECTION_ITEMS + 1,
        retainedBytes: 0,
        textCodeUnits: 0,
      }),
    ).toBe(false);
    expect(
      guiConfigCostWithinBrowserLimits({
        collectionItems: 0,
        retainedBytes: MAX_BROWSER_GUI_RETAINED_BYTES + 1,
        textCodeUnits: 0,
      }),
    ).toBe(false);
  });
});

describe("per-component collection admission", () => {
  const dropdown = (count: number, itemLength = 1): GuiDropdownMessage => ({
    type: "GuiDropdownMessage",
    uuid: "dropdown",
    value: "",
    container_uuid: "root",
    props: {
      order: 0,
      label: null,
      hint: null,
      visible: true,
      disabled: false,
      options: Array.from({ length: count }, () => "x".repeat(itemLength)),
      searchable: false,
    },
  });

  it("admits exactly 4,096 rows and rejects one more", () => {
    expect(
      guiConfigWithinEntityLimits(dropdown(MAX_GUI_COLLECTION_ITEMS)),
    ).toBe(true);
    expect(
      guiConfigWithinEntityLimits(dropdown(MAX_GUI_COLLECTION_ITEMS + 1)),
    ).toBe(false);
  });

  it("admits exact option text and rejects one more UTF-16 unit", () => {
    expect(
      guiConfigWithinEntityLimits(
        dropdown(1, MAX_GUI_COLLECTION_ITEM_CODE_UNITS),
      ),
    ).toBe(true);
    expect(
      guiConfigWithinEntityLimits(
        dropdown(1, MAX_GUI_COLLECTION_ITEM_CODE_UNITS + 1),
      ),
    ).toBe(false);
  });
  const radioList = (
    value: GuiRadioListMessage["value"],
  ): GuiRadioListMessage => ({
    type: "GuiRadioListMessage",
    uuid: "radio-list",
    value,
    container_uuid: "root",
    props: {
      order: 0,
      label: null,
      hint: null,
      visible: true,
      disabled: false,
      frozen: false,
    },
  });

  it("admits zero or one radio selection and rejects more", () => {
    expect(
      guiConfigWithinEntityLimits(
        radioList([
          ["one", false],
          ["two", true],
        ]),
      ),
    ).toBe(true);
    expect(
      guiConfigWithinEntityLimits(
        radioList([
          ["one", true],
          ["two", true],
        ]),
      ),
    ).toBe(false);
  });

  const button = (frequencies: number[]): GuiButtonMessage => ({
    type: "GuiButtonMessage",
    uuid: "button",
    value: false,
    container_uuid: "root",
    props: {
      order: 0,
      label: null,
      hint: null,
      visible: true,
      disabled: false,
      text: "Button",
      color: "default",
      _icon_html: null,
      _hold_callback_freqs: frequencies,
      _prefetch: false,
    },
  });

  it("admits 64 unique hold frequencies through 60Hz", () => {
    const exact = Array.from(
      { length: MAX_GUI_BUTTON_HOLD_FREQUENCIES },
      (_, index) =>
        ((index + 1) * MAX_GUI_BUTTON_HOLD_FREQUENCY_HZ) /
        MAX_GUI_BUTTON_HOLD_FREQUENCIES,
    );
    expect(guiConfigWithinEntityLimits(button(exact))).toBe(true);
    expect(guiConfigWithinEntityLimits(button([...exact, 0.5]))).toBe(false);
  });

  it("rejects duplicate, nonfinite, nonpositive, and over-60Hz holds", () => {
    for (const frequencies of [
      [1, 1],
      [Number.NaN],
      [Number.POSITIVE_INFINITY],
      [0],
      [-1],
      [MAX_GUI_BUTTON_HOLD_FREQUENCY_HZ + 0.001],
    ]) {
      expect(guiConfigWithinEntityLimits(button(frequencies))).toBe(false);
    }
  });

  it("defensively deduplicates and bounds directly rendered frequencies", () => {
    const exact = Array.from(
      { length: MAX_GUI_BUTTON_HOLD_FREQUENCIES },
      (_, index) =>
        ((index + 1) * MAX_GUI_BUTTON_HOLD_FREQUENCY_HZ) /
        MAX_GUI_BUTTON_HOLD_FREQUENCIES,
    );
    const hostile = [
      ...exact,
      exact[0],
      0,
      Number.NaN,
      MAX_GUI_BUTTON_HOLD_FREQUENCY_HZ + 1,
    ];
    const bounded = boundedHoldCallbackFrequencies(hostile);
    expect(bounded).toHaveLength(MAX_GUI_BUTTON_HOLD_FREQUENCIES);
    expect(new Set(bounded).size).toBe(bounded.length);
    expect(
      bounded.every(
        (frequency) =>
          frequency > 0 && frequency <= MAX_GUI_BUTTON_HOLD_FREQUENCY_HZ,
      ),
    ).toBe(true);
  });
});

describe("specialized GUI source admission", () => {
  it("enforces HTML, Plotly, and Markdown source caps at exact boundaries", () => {
    const html: GuiHtmlMessage = {
      type: "GuiHtmlMessage",
      uuid: "html",
      container_uuid: "root",
      props: { order: 0, content: "", visible: true },
    };
    html.props.content = "x".repeat(GUI_HTML_MAX_SOURCE_CODE_UNITS);
    expect(guiConfigWithinEntityLimits(html)).toBe(true);
    html.props.content += "x";
    expect(guiConfigWithinEntityLimits(html)).toBe(false);

    const plotly: GuiPlotlyMessage = {
      type: "GuiPlotlyMessage",
      uuid: "plotly",
      container_uuid: "root",
      props: {
        order: 0,
        _plotly_json_str: "x".repeat(PLOTLY_JSON_MAX_SERIALIZED_CHARACTERS),
        aspect: 1,
        visible: true,
      },
    };
    expect(guiConfigWithinEntityLimits(plotly)).toBe(true);
    plotly.props._plotly_json_str += "x";
    expect(guiConfigWithinEntityLimits(plotly)).toBe(false);

    const text: GuiTextMessage = {
      type: "GuiTextMessage",
      uuid: "text",
      value: "value",
      container_uuid: "root",
      props: {
        order: 0,
        label: null,
        hint: null,
        visible: true,
        disabled: false,
        multiline: false,
        rows: null,
        editable: false,
        markdown: true,
        _source: "x".repeat(MAX_GUI_MARKDOWN_SOURCE_BYTES),
      },
    };
    expect(guiConfigWithinEntityLimits(text)).toBe(true);
    text.props._source += "x";
    expect(guiConfigWithinEntityLimits(text)).toBe(false);
  });

  it("rejects upload MIME controls before they reach a file input", () => {
    const upload: GuiUploadButtonMessage = {
      type: "GuiUploadButtonMessage",
      uuid: "upload",
      container_uuid: "root",
      props: {
        order: 0,
        label: null,
        hint: null,
        visible: true,
        disabled: false,
        text: "Upload",
        color: "default",
        _icon_html: null,
        mime_type: "image/png",
      },
    };
    expect(guiConfigWithinEntityLimits(upload)).toBe(true);
    upload.props.mime_type = "image/\ninvalid";
    expect(guiConfigWithinEntityLimits(upload)).toBe(false);
  });
});
