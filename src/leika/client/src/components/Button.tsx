import React, { useCallback, useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiButtonMessage } from "../WebsocketMessages";
import { HintTooltip } from "./common";

export default function ButtonComponent({
  uuid,
  props: {
    disabled,
    label,
    hint,
    color,
    _icon_html: iconHtml,
    _hold_callback_freqs: holdCallbackFreqs,
  },
}: GuiButtonMessage) {
  const { messageSender } = React.useContext(GuiComponentContext)!;
  const holdIntervalsRef = useRef<ReturnType<typeof setInterval>[]>([]);

  const stopHoldTimers = useCallback(() => {
    holdIntervalsRef.current.forEach(clearInterval);
    holdIntervalsRef.current = [];
  }, []);

  useEffect(() => stopHoldTimers, [stopHoldTimers]);
  useEffect(() => {
    if (disabled) stopHoldTimers();
  }, [disabled, stopHoldTimers]);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0 || holdCallbackFreqs.length === 0) return;
      if (holdIntervalsRef.current.length > 0) return;

      event.currentTarget.setPointerCapture(event.pointerId);
      for (const frequency of holdCallbackFreqs) {
        messageSender({
          type: "GuiButtonHoldMessage",
          uuid,
          frequency,
        });
        holdIntervalsRef.current.push(
          setInterval(
            () =>
              messageSender({
                type: "GuiButtonHoldMessage",
                uuid,
                frequency,
              }),
            1000 / frequency,
          ),
        );
      }
    },
    [holdCallbackFreqs, messageSender, uuid],
  );

  const button = (
    <Button
      id={uuid}
      // "secondary" is the settings pane's own outlined button rather than the
      // stock `secondary` variant, which is a second FILLED tone -- the point of
      // the pairing is one button that carries the accent and one that does not.
      variant={color === "secondary" ? "outline" : "default"}
      className="w-full"
      data-leika-button
      data-leika-button-color={color}
      onClick={() =>
        messageSender({
          type: "GuiUpdateMessage",
          uuid,
          updates: { value: true },
        })
      }
      onPointerDown={handlePointerDown}
      onPointerUp={stopHoldTimers}
      onPointerCancel={stopHoldTimers}
      onLostPointerCapture={stopHoldTimers}
      disabled={disabled ?? false}
    >
      {iconHtml === null ? null : (
        <span
          data-icon="inline-start"
          className="size-3.5 [&_svg]:size-full"
          dangerouslySetInnerHTML={{ __html: iconHtml }}
        />
      )}
      {label}
    </Button>
  );
  if (hint === null) return button;
  return (
    <HintTooltip hint={hint}>
      <span className="block w-full">{button}</span>
    </HintTooltip>
  );
}
