// Bridges the server's notification protocol onto the shadcn toast component.
//
// Server notifications are connection-owned. Keep their IDs separate from
// download/error toasts so reconnect cleanup closes only stale server state.

import { toast, type ToastData } from "./components/ui/toast";
import {
  MAX_BROWSER_LIVE_NOTIFICATIONS,
  MAX_NOTIFICATION_AUTO_CLOSE_MILLISECONDS,
  notificationWithinEntityLimits,
} from "./guiLimits";
import type { Message, NotificationShowMessage } from "./WebsocketMessages";

/** The server's notification props (inlined by the protocol generator). */
export type NotificationProps = NotificationShowMessage["props"];

export interface NotificationToastOptions {
  title: string;
  description: string | undefined;
  type: string | undefined;
  timeout: number;
  data: ToastData;
}

interface NotificationToastRuntime {
  add: (
    options: NotificationToastOptions & {
      id: string;
      onRemove: () => void;
    },
  ) => void;
  update: (uuid: string, options: NotificationToastOptions) => void;
  close: (uuid: string) => void;
}

export const MAX_BROWSER_NOTIFICATION_TEXT_CODE_UNITS = 4 * 1024 * 1024;

type NotificationOwner = {
  generation: object;
  props: NotificationProps;
  toastId: string;
};

function notificationTextCost(props: NotificationProps): number {
  return props.title.length + props.body.length;
}

/** Bounded ownership for server notifications from the active connection. */
export class ServerNotificationRegistry {
  private readonly owners = new Map<string, NotificationOwner>();
  private readonly freeSlots: number[] = [];
  private nextSlot = 0;

  constructor(
    private readonly runtime: NotificationToastRuntime,
    private readonly maxOwners = MAX_BROWSER_LIVE_NOTIFICATIONS,
    private readonly maxTextCodeUnits = MAX_BROWSER_NOTIFICATION_TEXT_CODE_UNITS,
  ) {}

  get size(): number {
    return this.owners.size;
  }

  private allocateToastId(): string | null {
    const slot = this.freeSlots.pop() ?? this.nextSlot;
    if (slot >= this.maxOwners) return null;
    if (slot === this.nextSlot) this.nextSlot += 1;
    return `leika-server-notification-${slot}`;
  }

  private releaseToastId(toastId: string): void {
    const prefix = "leika-server-notification-";
    const slot = Number(toastId.slice(prefix.length));
    if (
      !toastId.startsWith(prefix) ||
      !Number.isSafeInteger(slot) ||
      slot < 0 ||
      slot >= this.nextSlot ||
      this.freeSlots.includes(slot)
    ) {
      throw new Error("notification toast slot accounting is invalid");
    }
    this.freeSlots.push(slot);
  }

  preflight(messages: readonly Message[]): string | null {
    const owners = new Map(
      [...this.owners].map(([uuid, owner]) => [uuid, owner.props]),
    );
    let textCodeUnits = 0;
    for (const props of owners.values())
      textCodeUnits += notificationTextCost(props);
    for (const message of messages) {
      if (message.type === "NotificationShowMessage") {
        if (!notificationWithinEntityLimits(message.props)) {
          return "notification exceeds its string limit";
        }
        if (!owners.has(message.uuid) && owners.size >= this.maxOwners) {
          return "notification owner limit exceeded";
        }
        const previous = owners.get(message.uuid);
        textCodeUnits +=
          notificationTextCost(message.props) -
          (previous === undefined ? 0 : notificationTextCost(previous));
        if (textCodeUnits > this.maxTextCodeUnits) {
          return "notification text budget exceeded";
        }
        owners.set(message.uuid, message.props);
      } else if (message.type === "NotificationUpdateMessage") {
        if (
          owners.has(message.uuid) &&
          !notificationWithinEntityLimits(message.props)
        ) {
          return "notification update exceeds its string limit";
        }
        const previous = owners.get(message.uuid);
        if (previous !== undefined) {
          textCodeUnits +=
            notificationTextCost(message.props) -
            notificationTextCost(previous);
          if (textCodeUnits > this.maxTextCodeUnits) {
            return "notification text budget exceeded";
          }
          owners.set(message.uuid, message.props);
        }
      } else if (message.type === "RemoveNotificationMessage") {
        const previous = owners.get(message.uuid);
        if (previous !== undefined)
          textCodeUnits -= notificationTextCost(previous);
        owners.delete(message.uuid);
      }
    }
    return null;
  }

  show(uuid: string, props: NotificationProps): boolean {
    if (!notificationWithinEntityLimits(props)) {
      console.error(
        "Rejected notification that exceeded browser safety limits.",
      );
      return false;
    }
    const previous = this.owners.get(uuid);
    if (previous === undefined && this.owners.size >= this.maxOwners) {
      console.error(
        "Rejected notification that exceeded the browser owner limit.",
      );
      return false;
    }
    let textCodeUnits = notificationTextCost(props);
    for (const [id, owner] of this.owners) {
      if (id !== uuid) textCodeUnits += notificationTextCost(owner.props);
    }
    if (textCodeUnits > this.maxTextCodeUnits) {
      console.error(
        "Rejected notification that exceeded the browser text budget.",
      );
      return false;
    }
    const toastId = previous?.toastId ?? this.allocateToastId();
    if (toastId === null) {
      console.error(
        "Rejected notification that exceeded the browser owner limit.",
      );
      return false;
    }
    const owner: NotificationOwner = { generation: {}, props, toastId };
    this.owners.set(uuid, owner);
    try {
      this.runtime.add({
        id: toastId,
        ...toastOptionsFor(props),
        onRemove: () => {
          if (this.owners.get(uuid) !== owner) return;
          this.owners.delete(uuid);
          this.releaseToastId(owner.toastId);
        },
      });
      return true;
    } catch (error) {
      if (this.owners.get(uuid) === owner) {
        if (previous === undefined) {
          this.owners.delete(uuid);
          this.releaseToastId(toastId);
        } else this.owners.set(uuid, previous);
      }
      console.error("Could not show server notification:", error);
      return false;
    }
  }

  update(uuid: string, props: NotificationProps): boolean {
    const previous = this.owners.get(uuid);
    if (previous === undefined) return false;
    if (!notificationWithinEntityLimits(props)) {
      console.error(
        "Rejected notification update that exceeded browser safety limits.",
      );
      return false;
    }
    let textCodeUnits = notificationTextCost(props);
    for (const [id, owner] of this.owners) {
      if (id !== uuid) textCodeUnits += notificationTextCost(owner.props);
    }
    if (textCodeUnits > this.maxTextCodeUnits) {
      console.error(
        "Rejected notification update that exceeded the browser text budget.",
      );
      return false;
    }
    try {
      this.runtime.update(previous.toastId, toastOptionsFor(props));
      previous.props = props;
      return true;
    } catch (error) {
      console.error("Could not update server notification:", error);
      return false;
    }
  }

  dismiss(uuid: string): void {
    const owner = this.owners.get(uuid);
    if (owner === undefined) return;
    // Logical ownership is terminal immediately, matching frame preflight.
    // Reusing this fixed slot makes Base UI replace an ending toast instead
    // of retaining an unbounded trail of closing DOM nodes.
    this.owners.delete(uuid);
    this.releaseToastId(owner.toastId);
    try {
      this.runtime.close(owner.toastId);
    } catch (error) {
      console.error("Could not close server notification:", error);
    }
  }

  reset(): void {
    const toastIds = [...this.owners.values()].map((owner) => owner.toastId);
    this.owners.clear();
    this.freeSlots.length = 0;
    this.nextSlot = 0;
    for (const toastId of toastIds) {
      try {
        this.runtime.close(toastId);
      } catch (error) {
        console.error("Could not close stale server notification:", error);
      }
    }
  }
}

const serverNotifications = new ServerNotificationRegistry(toast);

/** Translate one notification's props into toast manager options. */
export function toastOptionsFor(
  props: NotificationProps,
): NotificationToastOptions {
  return {
    title: props.title,
    // An empty body would otherwise render an empty description line under
    // the title, which reads as a layout bug rather than an absent body.
    description: props.body === "" ? undefined : props.body,
    // Selects the toast's icon; "loading" is the spinner. Anything else is an
    // ordinary notification, which the protocol has no severity levels for.
    type: props.loading ? "loading" : undefined,
    // The protocol counts seconds and treats null as "stay until dismissed";
    // the toast manager counts milliseconds and spells that same case 0.
    timeout:
      props.auto_close_seconds === null
        ? 0
        : Math.min(
            MAX_NOTIFICATION_AUTO_CLOSE_MILLISECONDS,
            Math.max(0, props.auto_close_seconds * 1_000),
          ),
    data: { closeButton: props.with_close_button },
  };
}

export function showNotification(uuid: string, props: NotificationProps): void {
  serverNotifications.show(uuid, props);
}

export function updateNotification(
  uuid: string,
  props: NotificationProps,
): void {
  serverNotifications.update(uuid, props);
}

export function dismissNotification(uuid: string): void {
  serverNotifications.dismiss(uuid);
}

export function resetNotifications(): void {
  serverNotifications.reset();
}

export function preflightNotificationBatch(
  messages: readonly Message[],
): string | null {
  return serverNotifications.preflight(messages);
}

export interface FileDownloadToastOptions {
  title: string;
  link: { href: string; download: string };
  timeout: number;
  data: ToastData;
}

/** Toast options for offering a finished download as a link.
 *
 * Used when the server sends `save_immediately=false`: instead of saving on the
 * user's behalf, the client surfaces a link they can click -- or right click
 * and "Save as..." to choose a location themselves.
 */
export function fileDownloadToastOptions(
  filename: string,
  href: string,
): FileDownloadToastOptions {
  return {
    title: filename,
    link: { href, download: filename },
    // The object URL is revoked once the toast is removed, so auto-closing
    // would revoke the link out from under a user who hadn't clicked it yet.
    timeout: 0,
    data: { closeButton: true },
  };
}
