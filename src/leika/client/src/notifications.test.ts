import { describe, expect, it } from "vitest";
import {
  fileDownloadToastOptions,
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

describe("toastOptionsFor", () => {
  it("maps title and body onto the toast's title and description", () => {
    const options = toastOptionsFor(props());
    expect(options.title).toBe("Export finished");
    expect(options.description).toBe("Wrote 12 files.");
  });

  it("omits the description for an empty body", () => {
    // Passing "" would render an empty line under the title.
    expect(toastOptionsFor(props({ body: "" })).description).toBeUndefined();
  });

  it("marks a loading notification so it renders the spinner", () => {
    expect(toastOptionsFor(props({ loading: true })).type).toBe("loading");
    expect(toastOptionsFor(props({ loading: false })).type).toBeUndefined();
  });

  describe("auto-close", () => {
    it("converts seconds to milliseconds", () => {
      expect(toastOptionsFor(props({ auto_close_seconds: 5 })).timeout).toBe(
        5000,
      );
      expect(toastOptionsFor(props({ auto_close_seconds: 0.5 })).timeout).toBe(
        500,
      );
    });

    it("treats null as stay-until-dismissed", () => {
      // 0 is the toast manager's spelling of "never auto-dismiss".
      expect(toastOptionsFor(props({ auto_close_seconds: null })).timeout).toBe(
        0,
      );
    });

    it("treats zero seconds as stay-until-dismissed too", () => {
      expect(toastOptionsFor(props({ auto_close_seconds: 0 })).timeout).toBe(0);
    });
  });

  it("carries the close-button choice through to the toast data", () => {
    expect(toastOptionsFor(props({ with_close_button: true })).data).toEqual({
      closeButton: true,
    });
    expect(toastOptionsFor(props({ with_close_button: false })).data).toEqual({
      closeButton: false,
    });
  });
});

describe("fileDownloadToastOptions", () => {
  const options = () => fileDownloadToastOptions("signal.csv", "blob:abc123");

  it("titles the toast with the filename", () => {
    expect(options().title).toBe("signal.csv");
  });

  it("points the link at the blob and names the saved file", () => {
    // The download attribute is what makes right click -> "Save as..." offer
    // the server's filename rather than the opaque blob uuid.
    expect(options().link).toEqual({
      href: "blob:abc123",
      download: "signal.csv",
    });
  });

  it("never auto-closes, so the link outlives the default toast timeout", () => {
    // The object URL is revoked on removal; auto-closing would break the link
    // before the user had a chance to click it.
    expect(options().timeout).toBe(0);
  });

  it("always offers a close button, since nothing else dismisses it", () => {
    expect(options().data).toEqual({ closeButton: true });
  });
});
