import React, { useCallback, useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GUI_MESSAGE_THROTTLE_MS } from "../WebsocketUtils";
import { GuiButtonMessage } from "../WebsocketMessages";
import { GuiButtonRow, IconHtml } from "./common";

export default function ButtonComponent({
  uuid,
  props: {
    disabled,
    label,
    text,
    hint,
    color,
    _icon_html: iconHtml,
    _hold_callback_freqs: holdCallbackFreqs,
  },
}: GuiButtonMessage) {
  const { messageSender } = React.useContext(GuiComponentContext)!;
  const holdIntervalsRef = useRef<ReturnType<typeof setInterval>[]>([]);
  const holdFrequencies = React.useMemo(
    () =>
      holdCallbackFreqs.filter(
        (frequency) => Number.isFinite(frequency) && frequency > 0,
      ),
    [holdCallbackFreqs],
  );

  const stopHoldTimers = useCallback(() => {
    holdIntervalsRef.current.forEach(clearInterval);
    holdIntervalsRef.current = [];
  }, []);

  useEffect(() => stopHoldTimers, [holdFrequencies, stopHoldTimers]);
  useEffect(() => {
    if (disabled) stopHoldTimers();
  }, [disabled, stopHoldTimers]);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0 || holdFrequencies.length === 0) return;
      if (holdIntervalsRef.current.length > 0) return;

      event.currentTarget.setPointerCapture(event.pointerId);
      for (const frequency of holdFrequencies) {
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
            Math.max(GUI_MESSAGE_THROTTLE_MS, 1000 / frequency),
          ),
        );
      }
    },
    [holdFrequencies, messageSender, uuid],
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
        // A press, not a reading: two of them inside one throttle window are
        // two presses, and a row of buttons reports every one.
        messageSender(
          {
            type: "GuiUpdateMessage",
            uuid,
            updates: { value: true },
          },
          { coalesce: false },
        )
      }
      onPointerDown={handlePointerDown}
      onPointerUp={stopHoldTimers}
      onPointerCancel={stopHoldTimers}
      onLostPointerCapture={stopHoldTimers}
      disabled={disabled}
    >
      {iconHtml === null ? null : <IconHtml html={iconHtml} />}
      {text}
    </Button>
  );
  return (
    <GuiButtonRow {...{ uuid, label, hint, disabled }}>{button}</GuiButtonRow>
  );
}
