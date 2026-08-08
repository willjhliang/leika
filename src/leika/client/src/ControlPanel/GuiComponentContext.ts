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

export const GuiComponentContext =
  React.createContext<GuiComponentContext | null>(null);

/** Read generated-GUI services, failing loudly when the provider is absent. */
export function useGuiComponent(): GuiComponentContext {
  const context = React.useContext(GuiComponentContext);
  if (context === null) {
    throw new Error(
      "useGuiComponent must be used within GuiComponentContext.Provider",
    );
  }
  return context;
}
