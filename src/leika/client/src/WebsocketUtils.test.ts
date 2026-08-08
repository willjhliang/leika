import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Message } from "./WebsocketMessages";
import { ViewerContextContents } from "./ViewerContext";
import { makeThrottledMessageSender } from "./WebsocketUtils";
import { installConnectionBoundSender } from "./connectionSender";

const WINDOW_MS = 50;

function makeSender() {
  const sent: Message[] = [];
  const viewer = {
    mutable: {
      current: {
        sendMessage: (message: Message) => {
          sent.push(message);
        },
      },
    },
  } as unknown as ViewerContextContents;
  return { sent, viewer, ...makeThrottledMessageSender(viewer, WINDOW_MS) };
}

const value = (uuid: string, text: string) =>
  ({
    type: "GuiUpdateMessage",
    uuid,
    updates: { value: text },
  }) as unknown as Message;

const press = (uuid: string) =>
  ({
    type: "GuiUpdateMessage",
    uuid,
    updates: { value: true },
  }) as unknown as Message;

const submit = (uuid: string) =>
  ({ type: "GuiFormSubmitMessage", uuid }) as unknown as Message;

const hold = (uuid: string, frequency: number) =>
  ({ type: "GuiButtonHoldMessage", uuid, frequency }) as unknown as Message;

describe("makeThrottledMessageSender", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("sends the first message straight away", () => {
    const { send, sent } = makeSender();
    send(value("a", "one"));
    expect(sent).toHaveLength(1);
  });

  it("keeps the newest reading of one control and drops the rest", () => {
    const { send, sent } = makeSender();
    send(value("a", "one")); // Opens the window.
    send(value("a", "two"));
    send(value("a", "three"));
    vi.advanceTimersByTime(WINDOW_MS);
    expect(sent).toEqual([value("a", "one"), value("a", "three")]);
  });

  it("never lets one control's message displace another's", () => {
    // The panel shares one sender across every control it draws. With a single
    // pending slot, `b` overwrote `a` and `a` was never sent at all.
    const { send, sent } = makeSender();
    send(value("opener", "x")); // Opens the window.
    send(value("a", "typed"));
    send(value("b", "typed too"));
    vi.advanceTimersByTime(WINDOW_MS);
    expect(sent.slice(1)).toEqual([
      value("a", "typed"),
      value("b", "typed too"),
    ]);
  });

  it("commits an edit before the submit that follows it", () => {
    // The bug in the flesh: typing into a field and immediately submitting the
    // form around it dropped the typing, so `on_submit` read the old value.
    const { send, sent } = makeSender();
    send(press("open")); // Opens the window.
    send(value("field", "Grace"));
    send(submit("form"), { coalesce: false });
    vi.advanceTimersByTime(WINDOW_MS);
    expect(sent.slice(1)).toEqual([value("field", "Grace"), submit("form")]);
  });

  it("reports every press, including a repeat inside one window", () => {
    const { send, sent } = makeSender();
    send(press("go"), { coalesce: false });
    send(press("go"), { coalesce: false });
    send(press("go"), { coalesce: false });
    vi.advanceTimersByTime(WINDOW_MS);
    expect(sent).toHaveLength(3);
  });

  it("caps hold ticks per control rather than queueing them up", () => {
    const { send, sent } = makeSender();
    send(hold("go", 20));
    send(hold("go", 20));
    send(hold("go", 20));
    send(hold("go", 5));
    vi.advanceTimersByTime(WINDOW_MS);
    // One per frequency: the extras inside a window are the cap doing its job,
    // and a slower callback registered on the same button is not one of them.
    expect(sent).toEqual([hold("go", 20), hold("go", 20), hold("go", 5)]);
  });

  it("keeps rate-limiting across windows", () => {
    const { send, sent } = makeSender();
    send(value("a", "one"));
    send(value("a", "two"));
    vi.advanceTimersByTime(WINDOW_MS);
    send(value("a", "three"));
    expect(sent).toHaveLength(2);
    vi.advanceTimersByTime(WINDOW_MS);
    expect(sent).toEqual([
      value("a", "one"),
      value("a", "two"),
      value("a", "three"),
    ]);
  });

  it("drops what was waiting when cancelled, and sends the next at once", () => {
    const { send, sent, cancel } = makeSender();
    send(value("a", "one"));
    send(value("a", "two"));
    cancel();
    vi.advanceTimersByTime(WINDOW_MS);
    expect(sent).toEqual([value("a", "one")]);
    send(value("a", "three"));
    expect(sent).toHaveLength(2);
  });

  it("does not move a deferred message onto a replacement connection", () => {
    const { viewer, send } = makeSender();
    const firstConnection: Message[] = [];
    const replacementConnection: Message[] = [];
    installConnectionBoundSender(viewer.mutable.current, (message) =>
      firstConnection.push(message),
    );

    send(value("a", "one"));
    send(value("a", "two"));
    installConnectionBoundSender(viewer.mutable.current, (message) =>
      replacementConnection.push(message),
    );
    vi.advanceTimersByTime(WINDOW_MS);

    expect(firstConnection).toEqual([value("a", "one")]);
    expect(replacementConnection).toEqual([]);
    send(value("a", "three"));
    expect(replacementConnection).toEqual([value("a", "three")]);
  });
});
