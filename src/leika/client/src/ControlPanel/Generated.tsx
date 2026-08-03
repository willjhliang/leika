import { ViewerContext } from "../ViewerContext";
import { useThrottledMessageSender } from "../WebsocketUtils";
import { GuiComponentContext } from "./GuiComponentContext";
import { shallowObjectKeysEqual } from "../utils/shallowObjectKeysEqual";

import React from "react";
import ButtonComponent from "../components/Button";
import SliderComponent from "../components/Slider";
import NumberInputComponent from "../components/NumberInput";
import TextInputComponent from "../components/TextInput";
import ListInputComponent from "../components/ListInput";
import ChecklistComponent from "../components/Checklist";
import CheckboxComponent from "../components/Checkbox";
import Vector2Component from "../components/Vector2";
import Vector3Component from "../components/Vector3";
import DropdownComponent from "../components/Dropdown";
import RgbComponent from "../components/Rgb";
import RgbaComponent from "../components/Rgba";
import ButtonGroupComponent from "../components/ButtonGroup";
import ToggleComponent from "../components/Toggle";
import ToggleGroupComponent from "../components/ToggleGroup";
import PlotlyComponent from "../components/PlotlyComponent";
import TabGroupComponent from "../components/TabGroup";
import FolderComponent from "../components/Folder";
import FormComponent from "../components/Form";
import MultiSliderComponent from "../components/MultiSlider";
import UploadButtonComponent from "../components/UploadButton";
import ProgressBarComponent from "../components/ProgressBar";
import ImageComponent from "../components/Image";
import HtmlComponent from "../components/Html";
import DividerComponent from "../components/Divider";

/** Root of generated inputs. */
export default function GeneratedGuiContainer({
  containerUuid,
}: {
  containerUuid: string;
}) {
  const viewer = React.useContext(ViewerContext)!;
  const updateGuiProps = viewer.guiActions.updateGuiProps;
  const messageSender = useThrottledMessageSender(50).send;

  function setValue(uuid: string, value: NonNullable<unknown>) {
    updateGuiProps(uuid, { value });
    messageSender({
      type: "GuiUpdateMessage",
      uuid,
      updates: { value },
    });
  }
  return (
    <GuiComponentContext.Provider
      value={{
        GuiContainer,
        messageSender,
        setValue,
      }}
    >
      <GuiContainer containerUuid={containerUuid} />
    </GuiComponentContext.Provider>
  );
}

function GuiContainer({
  containerUuid,
  unwrapped = false,
}: {
  containerUuid: string;
  /** If true, render children directly into the nearest GUI stack. */
  unwrapped?: boolean;
}) {
  const viewer = React.useContext(ViewerContext)!;
  const guiIdSet = viewer.useGui(
    (state) => state.guiUuidSetFromContainerUuid[containerUuid] ?? {},
    shallowObjectKeysEqual,
  );
  const guiOrderFromId = viewer.useGui((state) => state.guiOrderFromUuid);
  const children = Object.keys(guiIdSet)
    .map((uuid) => ({ uuid, order: guiOrderFromId[uuid] }))
    .sort((a, b) => a.order - b.order)
    .map(({ uuid }) => <GeneratedInput key={uuid} guiUuid={uuid} />);

  if (unwrapped) return <>{children}</>;
  return (
    <div
      className="flex w-full min-w-0 flex-col gap-2"
      data-leika-gui-container
    >
      {children}
    </div>
  );
}

/** A single generated GUI element. */
function GeneratedInput(props: { guiUuid: string }) {
  const viewer = React.useContext(ViewerContext)!;
  const conf = viewer.useGuiConfig(props.guiUuid);
  if (conf === undefined) {
    console.error("Tried to render non-existent component", props.guiUuid);
    return null;
  }
  // Every GUI element carries `visible`, so it is honored once here rather
  // than re-implemented in each component. Hiding unmounts: an element that
  // comes back is rebuilt from the server's props, with no stale local state
  // from before it was hidden.
  if (!conf.props.visible) return null;
  switch (conf.type) {
    case "GuiFolderMessage":
      return <FolderComponent {...conf} />;
    case "GuiFormMessage":
      return <FormComponent {...conf} />;
    case "GuiTabGroupMessage":
      return <TabGroupComponent {...conf} />;
    case "GuiHtmlMessage":
      return <HtmlComponent {...conf} />;
    case "GuiDividerMessage":
      return <DividerComponent />;
    case "GuiPlotlyMessage":
      return <PlotlyComponent {...conf} />;
    case "GuiImageMessage":
      return <ImageComponent {...conf} />;
    case "GuiButtonMessage":
      return <ButtonComponent {...conf} />;
    case "GuiUploadButtonMessage":
      return <UploadButtonComponent {...conf} />;
    case "GuiSliderMessage":
      return <SliderComponent {...conf} />;
    case "GuiMultiSliderMessage":
      return <MultiSliderComponent {...conf} />;
    case "GuiNumberMessage":
      return <NumberInputComponent {...conf} />;
    case "GuiTextMessage":
      return <TextInputComponent {...conf} />;
    case "GuiListMessage":
      return <ListInputComponent {...conf} />;
    case "GuiChecklistMessage":
      return <ChecklistComponent {...conf} />;
    case "GuiCheckboxMessage":
      return <CheckboxComponent {...conf} />;
    case "GuiVector2Message":
      return <Vector2Component {...conf} />;
    case "GuiVector3Message":
      return <Vector3Component {...conf} />;
    case "GuiDropdownMessage":
      return <DropdownComponent {...conf} />;
    case "GuiRgbMessage":
      return <RgbComponent {...conf} />;
    case "GuiRgbaMessage":
      return <RgbaComponent {...conf} />;
    case "GuiButtonGroupMessage":
      return <ButtonGroupComponent {...conf} />;
    case "GuiToggleMessage":
      return <ToggleComponent {...conf} />;
    case "GuiToggleGroupMessage":
      return <ToggleGroupComponent {...conf} />;
    case "GuiProgressBarMessage":
      return <ProgressBarComponent {...conf} />;
    default:
      assertNeverType(conf);
  }
}

function assertNeverType(x: never): never {
  throw new Error("Unexpected object: " + (x as any).type);
}
