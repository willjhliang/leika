import * as React from "react";
import * as Messages from "../WebsocketMessages";

interface GuiComponentContext {
  setValue: (id: string, value: NonNullable<unknown>) => void;
  /** Throttled, and coalescing per component unless told otherwise: pass
   * `coalesce: false` for a message that reports something that HAPPENED
   * rather than what a control now reads (see makeThrottledMessageSender). */
  messageSender: (
    message: Messages.Message,
    options?: { coalesce?: boolean },
  ) => void;
  GuiContainer: React.FC<{ containerUuid: string; unwrapped?: boolean }>;
}

export const GuiComponentContext = React.createContext<GuiComponentContext>({
  setValue: () => undefined,
  messageSender: () => undefined,
  GuiContainer: () => {
    throw new Error("GuiComponentContext not initialized");
  },
});
