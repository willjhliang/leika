import * as React from "react";

import {
  connectionStats,
  useConnectionReading,
} from "../ConnectionStatsController";
import { LEIKA_PROTOCOL } from "../VersionInfo";
import { useViewer } from "../ViewerContext";
import { usePeekHold } from "../dock/DockContext";
import {
  QUALITY_LABELS,
  formatBytes,
  formatDuration,
  formatLatency,
  formatRate,
} from "../connectionStats";
import {
  guiLabelClassName,
  guiRowGridClassName,
} from "../components/guiLabelStyles";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "../components/ui/popover";
import { Status, StatusIndicator, StatusLabel } from "../components/ui/status";
import { cn } from "@/lib/utils";
import { POPOUT_WIDTH_CLASS } from "./controlWidth";

/** Websocket states, as the Status component's vocabulary. Leika has nothing
 * that maps to "maintenance", which the server would have to be up to report.
 * The wording is load-bearing: the browser tests wait for "Connecting..." to
 * leave the page before they touch anything. */
const CONNECTION_STATUS = {
  connected: { status: "online", text: "Connected" },
  reconnecting: { status: "degraded", text: "Connecting..." },
  inactive: { status: "offline", text: "Inactive" },
} as const;

/** One measurement: what it is on the left, what it reads on the right.
 *
 * On the panel's own label column, so the popout lines up with the rows it
 * hangs beside rather than inventing a second grid. */
function StatRow({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className={cn(guiRowGridClassName, "gap-2")} data-leika-connection-row>
      <span className={cn("truncate text-sm", guiLabelClassName)} title={label}>
        {label}
      </span>
      {/* Typed like the value in a text field, which is what these are: the
          same size and color a row's own control would read at. Lining the
          figures up is the one addition -- a rate that reflows its digits
          every second is harder to read than one that does not. */}
      <span className="gui-row-controls min-w-0 truncate text-sm tabular-nums">
        {value}
        {detail !== undefined && (
          <span className="text-muted-foreground"> {detail}</span>
        )}
      </span>
    </div>
  );
}

/** What the connection is doing, measured in this browser.
 *
 * Everything here is the page's own view of the link: the server is asked for
 * nothing but an echo, so a reading that looks bad is bad from where the
 * reader is sitting, which is the only place it matters. */
function ConnectionRows() {
  const { useGui } = useViewer();
  const server = useGui((state) => state.server);
  const connectionError = useGui((state) => state.connectionError);
  const websocketState = useGui((state) => state.websocketState);
  const reading = useConnectionReading();

  return (
    <div className="flex flex-col gap-2" data-leika-connection-pane>
      {connectionError !== null && (
        <p
          className="text-xs text-destructive"
          data-leika-connection-error
          role="alert"
        >
          {connectionError}
        </p>
      )}
      <StatRow
        label="Quality"
        value={
          websocketState === "connected"
            ? QUALITY_LABELS[reading?.quality ?? "unknown"]
            : CONNECTION_STATUS[websocketState].text
        }
      />
      {/* The last round trip, with the middle of the window beside it: the
          verdict is the median's to give, and this is the number that moves
          the moment a link goes bad, before the window catches up. */}
      <StatRow
        label="Latency"
        value={formatLatency(reading?.latencyMs ?? null)}
        detail={
          reading?.medianLatencyMs != null
            ? `(median ${formatLatency(reading.medianLatencyMs)})`
            : undefined
        }
      />
      <StatRow
        label="Down"
        value={formatRate(reading?.downBytesPerSec ?? null)}
        detail={
          reading === null
            ? undefined
            : `(${formatBytes(reading.bytesReceived)} total)`
        }
      />
      <StatRow
        label="Up"
        value={formatRate(reading?.upBytesPerSec ?? null)}
        detail={
          reading === null
            ? undefined
            : `(${formatBytes(reading.bytesSent)} total)`
        }
      />
      <StatRow
        label="Messages"
        value={
          reading === null
            ? "--"
            : `${reading.messagesReceived} in, ${reading.messagesSent} out`
        }
      />
      <StatRow
        label="Connected"
        value={formatDuration(reading?.connectedForMs ?? null)}
        detail={
          reading !== null && reading.reconnects > 0
            ? `(${reading.reconnects} reconnect${reading.reconnects === 1 ? "" : "s"})`
            : undefined
        }
      />
      {/* Only when there is something to say: a row of zeroes reads as a
          problem measured, and there is no problem until one of these moves. */}
      {reading !== null && reading.droppedSends > 0 && (
        <StatRow
          label="Dropped"
          value={`${reading.droppedSends} sent while down`}
        />
      )}
      {reading !== null && reading.outOfOrderBatches > 0 && (
        <StatRow
          label="Out of order"
          value={`${reading.outOfOrderBatches} batches`}
        />
      )}
      {/* What a bug report would be asked for, next to the numbers that
          prompted it. The address says nothing about whether the page is
          reaching it -- the rows above are what answer that -- so it is stated
          rather than narrated. Selectable, so it can be copied rather than
          retyped. */}
      <div
        className="pt-0.5 text-center text-xs break-all text-muted-foreground select-text"
        data-leika-connection-about
      >
        {server} (Protocol {LEIKA_PROTOCOL}).
      </div>
    </div>
  );
}

/** The connection badge, and what it opens.
 *
 * Measuring costs a ping a second, so it happens only while this is open --
 * `watch` is what tells the worker to start, and dropping it is what stops it.
 */
export function ConnectionBadge() {
  const { useGui } = useViewer();
  const websocketState = useGui((state) => state.websocketState);
  const { status, text } = CONNECTION_STATUS[websocketState];
  const [open, setOpen] = React.useState(false);
  const badge = React.useRef<HTMLButtonElement>(null);

  React.useEffect(() => (open ? connectionStats.watch() : undefined), [open]);
  // Reaching for the popout means leaving the panel, which is what folds a
  // collapsed one away to this badge. Not while it is up.
  usePeekHold(open);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        // The pill IS the button rather than sitting inside one. A wrapper
        // would take the focus, leaving the pill to style itself off an
        // ancestor's state -- and Tailwind writes that ancestor into a
        // zero-specificity `:where()`, which the pill's own transparent border
        // then outranks. Rendered as one element, focus lands on the thing
        // that shows it, exactly as it does on the gear.
        render={
          <Status
            status={status}
            // Open, it fills with the accent the way the gear does --
            // `default` IS that pair of tokens -- so the two controls in the
            // header say "mine is the popout that is up" the same way.
            variant={open ? "default" : "secondary"}
            className={cn(
              // The hovers `Button` gives these same two variants. The Badge
              // base has its own, but they are scoped to anchors: a badge is
              // not usually something to press, and this one is.
              open
                ? "hover:bg-primary/80"
                : "hover:bg-[color-mix(in_oklch,var(--secondary),var(--foreground)_5%)]",
            )}
            render={
              <button
                ref={badge}
                type="button"
                // The panel header is the floating window's drag handle and
                // its click-to-collapse target, both driven from
                // `pointerdown`, so the gesture that opens this must not also
                // reach it.
                onPointerDown={(event) => event.stopPropagation()}
                aria-label="Connection details"
                // Collapsed, the floating panel fades down to this one thing,
                // so the peek marker rides on it.
                data-dock-peek
                data-leika-connection-trigger
              />
            }
          />
        }
      >
        {/* The dot keeps saying what the connection is -- that is the badge's
            job, and it is legible on either fill. */}
        <StatusIndicator />
        <StatusLabel className={open ? "text-primary-foreground" : undefined}>
          {text}
        </StatusLabel>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        // Aligned to the header rather than to the badge, for the reason the
        // settings popout is: the row's end is the panel's edge, and the badge
        // sits wherever the title's length leaves it.
        anchor={() =>
          badge.current?.closest("[data-leika-panel-header]") ?? badge.current
        }
        className={POPOUT_WIDTH_CLASS}
        data-leika-connection-popover
      >
        <PopoverHeader>
          <PopoverTitle data-leika-connection-title>Connection</PopoverTitle>
          <PopoverDescription className="sr-only">
            What this browser is measuring on its link to the server.
          </PopoverDescription>
        </PopoverHeader>
        <ConnectionRows />
      </PopoverContent>
    </Popover>
  );
}
