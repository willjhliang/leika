import * as React from "react";

import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiFolderMessage } from "../WebsocketMessages";
import { GuiSection, useContainerIsEmpty } from "./GuiSection";

export default function FolderComponent({
  uuid,
  props: { label, expand_by_default: expandByDefault },
}: GuiFolderMessage) {
  const guiContext = React.useContext(GuiComponentContext)!;
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
