import { PanelTopOpen } from "lucide-react";

import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GuiPopupMessage } from "../WebsocketMessages";
import { GuiPopout } from "./GuiPopout";

export default function PopupComponent({
  uuid,
  props: { label },
}: GuiPopupMessage) {
  const guiContext = useGuiComponent();

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
}
