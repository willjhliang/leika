import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createEntryStackDragController,
  moveEntryStackItem,
  settleEntryStackDrag,
  type EntryStackDrag,
  type EntryStackDragGeneration,
} from "./entryStackDrag";

type Listener = (event: Event) => void;

const pressed: EntryStackDrag = {
  entry: 0,
  origin: 20,
  stride: 24,
  pointerY: 20,
  grab: 0,
};

let listeners: Map<string, Set<Listener>>;

function dispatch(type: string, event: Partial<Event> = {}): void {
  for (const listener of [...(listeners.get(type) ?? [])]) {
    listener({ type, ...event } as Event);
  }
}

function countListeners(): number {
  return [...listeners.values()].reduce(
    (total, group) => total + group.size,
    0,
  );
}

function grip() {
  return {
    setPointerCapture: vi.fn(),
    releasePointerCapture: vi.fn(),
  } as unknown as Element;
}

beforeEach(() => {
  listeners = new Map();
  vi.stubGlobal("window", {
    addEventListener(type: string, listener: Listener) {
      const group = listeners.get(type) ?? new Set<Listener>();
      group.add(listener);
      listeners.set(type, group);
    },
    removeEventListener(type: string, listener: Listener) {
      listeners.get(type)?.delete(listener);
    },
  });
  vi.stubGlobal(
    "PointerEvent",
    class {
      type: string;
      pointerId: number;

      constructor(type: string, init: { pointerId?: number } = {}) {
        this.type = type;
        this.pointerId = init.pointerId ?? 0;
      }
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EntryStack pointer sessions", () => {
  it("commits the latest same-turn movement and owns listeners only in flight", () => {
    const items = ["one", "two", "three"];
    const generation: EntryStackDragGeneration = {
      items,
      disabled: false,
      frozen: false,
    };
    const draws: (EntryStackDrag | null)[] = [];
    let committed = items;
    const finish = vi.fn((drag: EntryStackDrag, dropped: boolean) => {
      const { place } = settleEntryStackDrag(drag, items.length, dropped);
      committed = moveEntryStackItem(items, drag.entry, place);
    });
    const control = createEntryStackDragController(generation, (drag) =>
      draws.push(drag),
    );
    const handle = grip();

    expect(countListeners()).toBe(0);
    expect(
      control.start({
        grip: handle,
        pointerId: 7,
        drag: pressed,
        finish,
      }),
    ).toBe(true);
    expect(countListeners()).toBe(4);
    control.sync({ ...generation });
    expect(countListeners()).toBe(4);

    // Move and release in one JavaScript turn, before a React render could
    // replace the drawn `pressed` value.
    dispatch("pointermove", { pointerId: 7, clientY: 68 } as PointerEvent);
    dispatch("pointerup", { pointerId: 7, clientY: 68 } as PointerEvent);

    expect(committed).toEqual(["two", "three", "one"]);
    expect(finish).toHaveBeenCalledOnce();
    expect(finish).toHaveBeenCalledWith(
      expect.objectContaining({ pointerY: 68 }),
      true,
    );
    expect(draws.at(-1)).toBeNull();
    expect(countListeners()).toBe(0);
    expect(handle.releasePointerCapture).toHaveBeenCalledOnce();
  });

  it("ignores foreign pointers and cancels exactly once", () => {
    const items = ["one", "two", "three"];
    const generation = { items, disabled: false, frozen: false };
    const draw = vi.fn();
    const finish = vi.fn();
    const control = createEntryStackDragController(generation, draw);
    const firstGrip = grip();

    expect(
      control.start({
        grip: firstGrip,
        pointerId: 7,
        drag: pressed,
        finish,
      }),
    ).toBe(true);
    expect(
      control.start({ grip: grip(), pointerId: 8, drag: pressed, finish }),
    ).toBe(false);
    dispatch("pointermove", { pointerId: 8, clientY: 68 } as PointerEvent);
    dispatch("pointerup", { pointerId: 8, clientY: 68 } as PointerEvent);
    expect(finish).not.toHaveBeenCalled();
    expect(draw).toHaveBeenCalledTimes(1);

    dispatch("pointercancel", {
      pointerId: 7,
      clientY: 20,
    } as PointerEvent);
    dispatch("pointerup", { pointerId: 7, clientY: 20 } as PointerEvent);
    expect(finish).toHaveBeenCalledOnce();
    expect(finish).toHaveBeenCalledWith(pressed, false);
    expect(countListeners()).toBe(0);

    const secondGrip = grip();
    expect(
      control.start({
        grip: secondGrip,
        pointerId: 8,
        drag: pressed,
        finish,
      }),
    ).toBe(true);
    dispatch("keydown", { key: "Escape" } as KeyboardEvent);
    expect(finish).toHaveBeenCalledTimes(2);
    expect(finish).toHaveBeenLastCalledWith(pressed, false);
    expect(countListeners()).toBe(0);
  });

  it("invalidates changed collections and disposes without committing", () => {
    const items = ["one", "two", "three"];
    const draw = vi.fn();
    const finish = vi.fn();
    const control = createEntryStackDragController(
      { items, disabled: false, frozen: false },
      draw,
    );

    const start = () =>
      control.start({
        grip: grip(),
        pointerId: 7,
        drag: pressed,
        finish,
      });

    expect(start()).toBe(true);
    control.sync({ items: items.slice(0, 1), disabled: false, frozen: false });
    dispatch("pointerup", { pointerId: 7 } as PointerEvent);
    expect(finish).not.toHaveBeenCalled();
    expect(draw).toHaveBeenLastCalledWith(null);
    expect(countListeners()).toBe(0);

    control.sync({ items, disabled: false, frozen: false });
    expect(start()).toBe(true);
    control.sync({ items, disabled: true, frozen: false });
    expect(finish).not.toHaveBeenCalled();
    expect(start()).toBe(false);

    control.sync({ items, disabled: false, frozen: false });
    expect(start()).toBe(true);
    control.sync({ items, disabled: false, frozen: true });
    expect(finish).not.toHaveBeenCalled();
    expect(start()).toBe(false);

    control.sync({ items, disabled: false, frozen: false });
    expect(start()).toBe(true);
    const drawsBeforeDispose = draw.mock.calls.length;
    control.dispose();
    dispatch("pointerup", { pointerId: 7 } as PointerEvent);
    expect(finish).not.toHaveBeenCalled();
    expect(draw).toHaveBeenCalledTimes(drawsBeforeDispose);
    expect(countListeners()).toBe(0);
  });
});
