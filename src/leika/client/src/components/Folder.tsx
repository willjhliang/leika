import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GuiFolderMessage } from "../WebsocketMessages";
import { GuiSection } from "./GuiSection";
import { useContainerIsEmpty } from "./useContainerIsEmpty";

export default function FolderComponent({
  uuid,
  props: { label, expand_by_default: expandByDefault },
}: GuiFolderMessage) {
  const guiContext = useGuiComponent();
  const isEmpty = useContainerIsEmpty(uuid);

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
