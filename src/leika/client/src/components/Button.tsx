import React, { useCallback, useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GUI_MESSAGE_THROTTLE_MS } from "../WebsocketUtils";
import { GuiButtonMessage } from "../WebsocketMessages";
import { ButtonLabel, GuiButtonRow, IconHtml } from "./common";

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
    _prefetch: prefetch,
  },
}: GuiButtonMessage) {
  const { messageSender } = useGuiComponent();

  // A button whose press shows a file asks for the file when it scrolls into
  // view, so that the press finds it already in the browser
  // (`GuiPreviewWarmMessage`; the server answers with a `warm` transfer that
  // is held rather than shown). Asked once per time on screen: the observer
  // disconnects after firing, and only a remount asks again.
  useEffect(() => {
    if (!prefetch) return;
    const node = document.getElementById(uuid);
    if (node === null) return;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      messageSender({ type: "GuiPreviewWarmMessage", uuid });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [prefetch, uuid, messageSender]);
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
      // Leika's roles and shadcn's variant names collide head-on: our
      // "default" is the OUTLINED one, while shadcn's `default` variant is the
      // filled one. Stock `secondary` is no use as the outlined role either --
      // it is a second FILLED tone, and the point of the pairing is one button
      // that carries the accent and one that does not.
      variant={color === "inverse" ? "default" : "outline"}
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
      <ButtonLabel>{text}</ButtonLabel>
    </Button>
  );
  return (
    <GuiButtonRow {...{ uuid, label, hint, disabled }}>{button}</GuiButtonRow>
  );
}
