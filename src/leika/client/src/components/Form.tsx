import * as React from "react";

import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { ViewerContext } from "../ViewerContext";
import { GuiFormMessage } from "../WebsocketMessages";
import { GuiSection, useContainerIsEmpty } from "./GuiSection";

/** A folder whose child values are committed together through native form
 * submission semantics. */
export default function FormComponent({
  uuid,
  props: { label, expand_by_default: expandByDefault },
}: GuiFormMessage) {
  const viewer = React.useContext(ViewerContext)!;
  const guiContext = React.useContext(GuiComponentContext)!;
  const isDirty = viewer.useGui((state) => state.dirtyFormUuids[uuid] === true);
  const isEmpty = useContainerIsEmpty(uuid);

  const onSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    guiContext.messageSender({ type: "GuiFormSubmitMessage", uuid });
  };
  const onChange = () => {
    if (isDirty) return;
    viewer.guiActions.setFormDirty(uuid);
    guiContext.messageSender({ type: "GuiFormDirtyMessage", uuid });
  };
  const contents = (
    <guiContext.GuiContainer containerUuid={uuid} unwrapped={label === null} />
  );

  if (label === null) {
    return (
      <form
        className="flex w-full min-w-0 flex-col gap-3"
        onSubmit={onSubmit}
        onChange={onChange}
      >
        <button type="submit" hidden tabIndex={-1} />
        {contents}
      </form>
    );
  }

  return (
    <form onSubmit={onSubmit} onChange={onChange} data-leika-section="form">
      <button type="submit" hidden tabIndex={-1} />
      <GuiSection
        uuid={uuid}
        label={label}
        expandByDefault={expandByDefault}
        isEmpty={isEmpty}
        triggerTitle={isDirty ? "Contains unsubmitted changes." : undefined}
        triggerSuffix={
          isDirty ? <span aria-label="unsubmitted changes">*</span> : null
        }
      >
        {contents}
      </GuiSection>
    </form>
  );
}
