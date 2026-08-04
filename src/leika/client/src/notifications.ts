// Bridges the server's notification protocol onto the shadcn toast component.
//
// The toast manager already provides the bookkeeping this used to need: toasts
// are keyed by a caller-supplied id, `add` with an existing id upserts in
// place, and `update` / `close` on an unknown -- or already dismissed --
// toast are silent no-ops. So the server's notification uuid is used directly
// as the toast id, and the client keeps no record of which notifications are
// live. A notification the user has already dismissed simply stops responding
// to updates, which is what a dismissal should mean.

import { toast, type ToastData } from "./components/ui/toast";
import type { NotificationShowMessage } from "./WebsocketMessages";

/** The server's notification props (inlined by the protocol generator). */
export type NotificationProps = NotificationShowMessage["props"];

export interface NotificationToastOptions {
  title: string;
  description: string | undefined;
  type: string | undefined;
  timeout: number;
  data: ToastData;
}

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
      props.auto_close_seconds === null ? 0 : props.auto_close_seconds * 1000,
    data: { closeButton: props.with_close_button },
  };
}

export function showNotification(uuid: string, props: NotificationProps): void {
  toast.add({ id: uuid, ...toastOptionsFor(props) });
}

export function updateNotification(
  uuid: string,
  props: NotificationProps,
): void {
  toast.update(uuid, toastOptionsFor(props));
}

export function dismissNotification(uuid: string): void {
  toast.close(uuid);
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
