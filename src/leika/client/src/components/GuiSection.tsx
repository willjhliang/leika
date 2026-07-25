import * as React from "react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { ViewerContext } from "../ViewerContext";
import { shallowObjectKeysEqual } from "../utils/shallowObjectKeysEqual";

/** True when a GUI container holds no children, which disables its section. */
export function useContainerIsEmpty(containerUuid: string): boolean {
  const viewer = React.useContext(ViewerContext)!;
  const guiIdSet = viewer.useGui(
    (state) => state.guiUuidSetFromContainerUuid[containerUuid],
    shallowObjectKeysEqual,
  );
  return guiIdSet === undefined || Object.keys(guiIdSet).length === 0;
}

/** Collapsible chrome shared by folders and forms. */
export function GuiSection({
  uuid,
  label,
  kind,
  expandByDefault,
  isEmpty,
  triggerTitle,
  triggerSuffix,
  children,
}: {
  uuid: string;
  label: string;
  /** Applied as `data-leika-section` unless the caller marks its own root. */
  kind?: "folder";
  expandByDefault: boolean;
  isEmpty: boolean;
  triggerTitle?: string;
  triggerSuffix?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [opened, setOpened] = React.useState(expandByDefault);
  return (
    <Accordion
      value={opened && !isEmpty ? [uuid] : []}
      onValueChange={(next) => setOpened(next.includes(uuid))}
      data-leika-section={kind}
    >
      <AccordionItem value={uuid} disabled={isEmpty}>
        <AccordionTrigger data-leika-section-trigger title={triggerTitle}>
          {label}
          {triggerSuffix}
        </AccordionTrigger>
        <AccordionContent data-leika-section-contents>
          {children}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
