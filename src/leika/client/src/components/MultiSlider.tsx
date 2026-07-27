import React from "react";

import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiMultiSliderMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";
import { MultiSlider } from "./MultiSliderComponent";

export default function MultiSliderComponent({
  uuid,
  value,
  props: {
    label,
    hint,
    disabled,
    min,
    max,
    precision,
    step,
    _marks: marks,
    fixed_endpoints: fixedEndpoints,
    min_range: minRange,
  },
}: GuiMultiSliderMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }}>
      <MultiSlider
        id={uuid}
        min={min}
        max={max}
        step={step ?? undefined}
        fixedEndpoints={fixedEndpoints}
        precision={precision}
        minRange={minRange ?? undefined}
        marks={marks}
        value={value}
        onChange={(next) => setValue(uuid, next)}
        disabled={disabled}
        label={label}
      />
    </GuiInputRow>
  );
}
