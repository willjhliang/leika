import { PanelTopOpen } from "lucide-react";

import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GuiFolderMessage } from "../WebsocketMessages";
import { GuiPopout } from "./GuiPopout";
import { GuiSection } from "./GuiSection";
import { useContainerIsEmpty } from "./useContainerIsEmpty";

/** A folder: a collapsible section of the panel, a plain group without a
 * label, or with `popup` one labelled row whose children open in a popout. */
export default function FolderComponent({
  uuid,
  props: { label, expand_by_default: expandByDefault, popup },
}: GuiFolderMessage) {
  const guiContext = useGuiComponent();
  const isEmpty = useContainerIsEmpty(uuid);

  if (popup && label !== null)
    return (
      <GuiPopout
        uuid={uuid}
        label={label}
        kind="popup"
        triggerText="Open popup"
        icon={<PanelTopOpen data-icon="inline-start" />}
        description={`Controls in ${label}.`}
      >
        <guiContext.GuiContainer containerUuid={uuid} />
      </GuiPopout>
    );

  const contents = (
    <guiContext.GuiContainer containerUuid={uuid} unwrapped={label === null} />
  );
  if (label === null) return contents;

  return (
    <GuiSection
      uuid={uuid}
      label={label}
      expandByDefault={expandByDefault}
      isEmpty={isEmpty}
    >
      {contents}
    </GuiSection>
  );
}
