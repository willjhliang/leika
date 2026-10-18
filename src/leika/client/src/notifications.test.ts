import { describe, expect, it, vi } from "vitest";
import {
  ServerNotificationRegistry,
  fileDownloadToastOptions,
  toastOptionsFor,
  type NotificationProps,
} from "./notifications";
import { MAX_GUI_COMMON_STRING_CODE_UNITS } from "./guiLimits";
import {
  MAX_NOTIFICATION_AUTO_CLOSE_MILLISECONDS,
  MAX_NOTIFICATION_AUTO_CLOSE_SECONDS,
} from "./guiLimits";

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

describe("ServerNotificationRegistry", () => {
  function harness(maxOwners = 2, maxTextCodeUnits?: number) {
    const removals = new Map<string, () => void>();
    const runtime = {
      add: vi.fn(
        (
          options: ReturnType<typeof toastOptionsFor> & {
            id: string;
            onRemove: () => void;
          },
        ) => {
          removals.set(options.id, options.onRemove);
        },
      ),
      update: vi.fn(),
      close: vi.fn(),
    };
    return {
      registry: new ServerNotificationRegistry(
        runtime,
        maxOwners,
        maxTextCodeUnits,
      ),
      removals,
      runtime,
    };
  }

  it("bounds owners and releases exactly when the toast disappears", () => {
    const { registry, removals } = harness();
    expect(registry.show("first", props())).toBe(true);
    expect(registry.show("second", props())).toBe(true);
    expect(registry.show("overflow", props())).toBe(false);
    expect(registry.size).toBe(2);

    removals.get("leika-server-notification-0")!();
    expect(registry.size).toBe(1);
    expect(registry.show("replacement", props())).toBe(true);
    expect(registry.size).toBe(2);
  });

  it("keeps a reused UUID owned when an older generation is removed", () => {
    const { registry, removals } = harness();
    registry.show("shared", props({ title: "old" }));
    const toastId = "leika-server-notification-0";
    const removeOld = removals.get(toastId)!;
    registry.show("shared", props({ title: "new" }));

    removeOld();
    expect(registry.size).toBe(1);
    removals.get(toastId)!();
    expect(registry.size).toBe(0);
  });

  it("closes only its connection-owned IDs on reset and admits replay", () => {
    const { registry, runtime } = harness();
    registry.show("first", props());
    registry.show("second", props());

    registry.reset();

    expect(runtime.close).toHaveBeenCalledTimes(2);
    expect(runtime.close).toHaveBeenCalledWith("leika-server-notification-0");
    expect(runtime.close).toHaveBeenCalledWith("leika-server-notification-1");
    expect(registry.size).toBe(0);
    expect(registry.show("first", props())).toBe(true);
  });

  it("rejects oversized title/body on create and update", () => {
    const { registry, runtime } = harness();
    const oversized = "x".repeat(MAX_GUI_COMMON_STRING_CODE_UNITS + 1);
    expect(registry.show("bad", props({ title: oversized }))).toBe(false);
    expect(registry.show("valid", props())).toBe(true);
    expect(registry.update("valid", props({ body: oversized }))).toBe(false);
    expect(runtime.update).not.toHaveBeenCalled();
  });

  it("rejects negative and overflowing browser notification timers", () => {
    const { registry, runtime } = harness();
    expect(registry.show("negative", props({ auto_close_seconds: -1 }))).toBe(
      false,
    );
    expect(
      registry.show(
        "overflow",
        props({
          auto_close_seconds: MAX_NOTIFICATION_AUTO_CLOSE_SECONDS + 0.001,
        }),
      ),
    ).toBe(false);
    expect(
      registry.show(
        "exact",
        props({ auto_close_seconds: MAX_NOTIFICATION_AUTO_CLOSE_SECONDS }),
      ),
    ).toBe(true);
    expect(runtime.add).toHaveBeenCalledOnce();
    expect(runtime.add.mock.calls[0][0].timeout).toBe(
      MAX_NOTIFICATION_AUTO_CLOSE_MILLISECONDS,
    );
  });

  it("reserves aggregate text deltas and releases them on remove/reset", () => {
    const { registry, removals } = harness(4, 8);
    expect(registry.show("first", props({ title: "1234", body: "" }))).toBe(
      true,
    );
    expect(registry.show("second", props({ title: "5678", body: "" }))).toBe(
      true,
    );
    expect(registry.show("overflow", props({ title: "x", body: "" }))).toBe(
      false,
    );

    removals.get("leika-server-notification-0")!();
    expect(registry.show("replacement", props({ title: "x", body: "" }))).toBe(
      true,
    );
    registry.reset();
    expect(
      registry.show("after-reset", props({ title: "12345678", body: "" })),
    ).toBe(true);
  });

  it("matches preflight for an exact-cap remove then show transaction", () => {
    const { registry, removals, runtime } = harness(1);
    expect(registry.show("old", props())).toBe(true);
    const removeOld = removals.get("leika-server-notification-0")!;
    const frame = [
      { type: "RemoveNotificationMessage", uuid: "old" },
      { type: "NotificationShowMessage", uuid: "new", props: props() },
    ] as const;
    expect(registry.preflight(frame)).toBeNull();

    registry.dismiss("old");
    expect(registry.show("new", props())).toBe(true);
    expect(registry.size).toBe(1);
    expect(runtime.close).toHaveBeenCalledWith("leika-server-notification-0");
    expect(runtime.add).toHaveBeenLastCalledWith(
      expect.objectContaining({ id: "leika-server-notification-0" }),
    );

    // A late transition callback from the replaced toast cannot release the
    // new logical owner that now occupies the same bounded DOM slot.
    removeOld();
    expect(registry.size).toBe(1);
  });

  it("releases accounting and reuses the slot when close throws", () => {
    const { registry, runtime } = harness(1);
    expect(registry.show("old", props())).toBe(true);
    runtime.close.mockImplementationOnce(() => {
      throw new Error("close failed");
    });

    expect(() => registry.dismiss("old")).not.toThrow();
    expect(registry.size).toBe(0);
    expect(registry.show("new", props())).toBe(true);
    expect(runtime.add).toHaveBeenLastCalledWith(
      expect.objectContaining({ id: "leika-server-notification-0" }),
    );
  });
});
