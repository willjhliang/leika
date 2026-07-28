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
  children,
}: {
  uuid: string;
  label: string;
  /** Applied as `data-leika-section` unless the caller marks its own root. */
  kind?: "folder";
  expandByDefault: boolean;
  isEmpty: boolean;
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
        {/* Header and contents both run a step tighter than the stock 2.5:
            sections stack many rows deep in a narrow panel, so their padding
            keeps the same rhythm as the controls they hold. */}
        <AccordionTrigger data-leika-section-trigger className="py-2">
          {label}
        </AccordionTrigger>
        {/* The top padding is not rhythm, it is clearance. A panel that
            animates its own height has to clip, and a slider's thumb is drawn
            4px above the 4px track it is centred on -- so a slider as the first
            row sat flush against that clip and lost the top of its circle.
            Stock `pt-0` is what put it there. The 4px here is exactly that
            overhang, so the thumb lands on the clip edge rather than inside
            it: enough to draw the whole circle, with nothing to spare. */}
        <AccordionContent data-leika-section-contents className="pt-1 pb-2">
          {children}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
