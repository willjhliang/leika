import * as React from "react";

import { POPOUT_WIDTH_CLASS } from "../ControlPanel/controlWidth";
import { Button } from "./ui/button";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "./ui/popover";
import { ButtonLabel, GuiButtonRow } from "./common";
import { useContainerIsEmpty } from "./useContainerIsEmpty";

type GuiPopoutKind = "form" | "popup";

export function GuiPopout({
  uuid,
  label,
  kind,
  triggerText,
  icon,
  description,
  open,
  onOpenChange,
  children,
}: {
  uuid: string;
  label: string | null;
  kind: GuiPopoutKind;
  triggerText: string;
  icon: React.ReactNode;
  description: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}) {
  const isEmpty = useContainerIsEmpty(uuid);
  const [internalOpen, setInternalOpen] = React.useState(false);
  const resolvedOpen = open ?? internalOpen;
  const handleOpenChange = (nextOpen: boolean) => {
    if (open === undefined) setInternalOpen(nextOpen);
    onOpenChange?.(nextOpen);
  };
  React.useEffect(() => {
    if (!isEmpty || !resolvedOpen) return;
    if (open === undefined) setInternalOpen(false);
    onOpenChange?.(false);
  }, [isEmpty, onOpenChange, open, resolvedOpen]);
  const triggerData =
    kind === "form"
      ? { "data-leika-form-trigger": true }
      : { "data-leika-popup-trigger": true };
  const contentData =
    kind === "form"
      ? { "data-leika-form-popover": true }
      : { "data-leika-popup-popover": true };

  return (
    <Popover open={resolvedOpen} onOpenChange={handleOpenChange}>
      <GuiButtonRow uuid={uuid} label={label} hint={null}>
        <PopoverTrigger
          render={
            <Button
              id={uuid}
              variant="outline"
              className="w-full"
              disabled={isEmpty}
              data-leika-button
              data-leika-button-color="default"
              {...triggerData}
            />
          }
        >
          {icon}
          <ButtonLabel>{triggerText}</ButtonLabel>
        </PopoverTrigger>
      </GuiButtonRow>
      <PopoverContent
        align="end"
        className={POPOUT_WIDTH_CLASS}
        {...contentData}
      >
        <PopoverHeader className="sr-only">
          <PopoverTitle>{label ?? triggerText}</PopoverTitle>
          <PopoverDescription>{description}</PopoverDescription>
        </PopoverHeader>
        {children}
      </PopoverContent>
    </Popover>
  );
}
