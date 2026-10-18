import { expect, it, vi } from "vitest";
import { toast } from "./components/ui/toast";
import {
  dismissNotification,
  fileDownloadToastOptions,
  resetNotifications,
  showNotification,
  toastOptionsFor,
  type NotificationProps,
} from "./notifications";

const props = (
  overrides: Partial<NotificationProps> = {},
): NotificationProps => ({
  title: "Export finished",
  body: "Wrote 12 files.",
  loading: false,
  with_close_button: true,
  auto_close_seconds: 5,
  ...overrides,
});

it("renders a timed notification from its server properties", () => {
  expect(toastOptionsFor(props())).toEqual({
    title: "Export finished",
    description: "Wrote 12 files.",
    type: undefined,
    timeout: 5000,
    data: { closeButton: true },
  });
});

it("keeps a loading notification open without an empty description", () => {
  expect(
    toastOptionsFor(
      props({
        body: "",
        loading: true,
        auto_close_seconds: null,
        with_close_button: false,
      }),
    ),
  ).toMatchObject({
    description: undefined,
    type: "loading",
    timeout: 0,
    data: { closeButton: false },
  });
});

it("keeps a named download link available until dismissed", () => {
  expect(fileDownloadToastOptions("signal.csv", "blob:abc123")).toEqual({
    title: "signal.csv",
    link: { href: "blob:abc123", download: "signal.csv" },
    timeout: 0,
    data: { closeButton: true },
  });
});

it("uses the server uuid as the toast id and closes only those on reset", () => {
  const add = vi.spyOn(toast, "add");
  const close = vi.spyOn(toast, "close");
  showNotification("first", props());
  showNotification("second", props());
  dismissNotification("second");
  expect(add).toHaveBeenCalledWith(expect.objectContaining({ id: "first" }));
  expect(close).toHaveBeenCalledWith("second");

  close.mockClear();
  resetNotifications();
  expect(close.mock.calls.map(([id]) => id).sort()).toEqual([
    "first",
    "second",
  ]);
  close.mockClear();
  resetNotifications();
  expect(close).not.toHaveBeenCalled();
});
