import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { VideoPlayback } from "./videoPlayback";
import type { ViewportVideoPane } from "./ViewportState";

// Deterministic media adapter: a browser integration suite separately exercises
// real decoding, seeking, fullscreen, visibility and independent clients.
class Media extends EventTarget {
  paused = true;
  readyState = 4;
  duration = 5;
  error = null;
  ended = false;
  playbackRate = 1;
  seeking = false;
  private time = 0;
  get currentTime() {
    return this.time;
  }
  set currentTime(value: number) {
    this.time = value;
    this.seeking = true;
    this.dispatchEvent(new Event("seeking"));
  }
  finishSeek() {
    this.seeking = false;
    this.dispatchEvent(new Event("seeked"));
  }
  advance(seconds: number) {
    if (!this.paused)
      this.time = Math.min(
        this.duration,
        this.time + seconds * this.playbackRate,
      );
  }
  play() {
    this.paused = false;
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  }
  pause() {
    if (this.paused) return;
    this.paused = true;
    this.dispatchEvent(new Event("pause"));
  }
}
function pane(id: string, url = "/clip.mp4"): ViewportVideoPane {
  return {
    kind: "video",
    paneId: id,
    props: {
      _url: url,
      autoplay: true,
      loop: true,
      muted: true,
      controls: true,
      sync_group: "episode",
      fps: 10,
      title: id,
      visible: true,
      loading: false,
    },
  };
}
let clock = 0;
let callbacks: Map<number, FrameRequestCallback>;
let serial = 0;
let controller: VideoPlayback;
const videos: Media[] = [];
async function frame(seconds = 0) {
  clock += seconds * 1000;
  videos.forEach((v) => v.advance(seconds));
  const next = [...callbacks.values()];
  callbacks.clear();
  next.forEach((callback) => callback(clock));
  await Promise.resolve();
  await Promise.resolve();
}
beforeEach(() => {
  clock = 0;
  videos.length = 0;
  callbacks = new Map();
  vi.stubGlobal("document", { hidden: false });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callbacks.set(++serial, callback);
    return serial;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => callbacks.delete(id));
  vi.spyOn(performance, "now").mockImplementation(() => clock);
  controller = new VideoPlayback();
});
afterEach(() => {
  controller.dispose();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function attach(id: string) {
  const video = new Media();
  videos.push(video);
  const binding = controller.attach(id, video as unknown as HTMLVideoElement);
  binding.visible(true);
  return { video, binding };
}

it("waits for every declared visible member and freezes the clock during buffering", async () => {
  controller.configure(
    new Map([
      ["a", pane("a")],
      ["b", pane("b")],
    ]),
  );
  const { video: a } = attach("a");
  await frame();
  expect(a.paused).toBe(true);
  const { video: b } = attach("b");
  await frame();
  await frame();
  await frame(0.2);
  expect(a.paused || b.paused).toBe(false);
  b.readyState = 2;
  b.dispatchEvent(new Event("waiting"));
  await frame();
  const time = controller.state.get().time;
  expect(a.paused && b.paused).toBe(true);
  await frame(2);
  expect(controller.state.get().time).toBe(time);
  b.readyState = 4;
  b.dispatchEvent(new Event("canplay"));
  await frame();
  await frame();
  await frame(0.1);
  expect(controller.state.get().time).toBeCloseTo(time + 0.1);
});

it("seeks every member while paused, waits for seek completion, and steps at declared fps", async () => {
  controller.configure(
    new Map([
      ["a", pane("a")],
      ["b", pane("b")],
    ]),
  );
  const { video: a } = attach("a");
  const { video: b } = attach("b");
  await frame();
  await frame();
  controller.pause();
  controller.seek(2);
  expect([a.currentTime, b.currentTime]).toEqual([2, 2]);
  controller.play();
  a.finishSeek();
  await frame();
  expect(a.paused).toBe(true);
  b.finishSeek();
  await frame();
  await frame();
  expect(a.paused || b.paused).toBe(false);
  controller.step(1);
  expect(controller.state.get()).toMatchObject({ time: 2.1, paused: true });
  expect([a.currentTime, b.currentTime]).toEqual([2.1, 2.1]);
});

it("resynchronizes a hidden member and corrects drift without changing the chosen speed", async () => {
  controller.configure(
    new Map([
      ["a", pane("a")],
      ["b", pane("b")],
    ]),
  );
  const { video: a } = attach("a");
  const { video: b, binding } = attach("b");
  await frame();
  await frame();
  binding.visible(false);
  await frame(0.3);
  expect(b.paused).toBe(true);
  expect(a.paused).toBe(false);
  binding.visible(true);
  expect(b.currentTime).toBeCloseTo(a.currentTime);
  b.finishSeek();
  await frame();
  await frame();
  controller.setRate(2);
  await frame();
  await frame(0.1);
  // A delayed decoder falls behind its clock without an application seek.
  b.advance(-0.2);
  await frame();
  expect(a.paused && b.paused).toBe(true);
  expect(b.currentTime).toBeCloseTo(a.currentTime);
  expect(controller.state.get().rate).toBe(2);
});

it("holds shorter media until the common end then loops through one seek barrier", async () => {
  controller.configure(
    new Map([
      ["a", pane("a")],
      ["b", pane("b")],
    ]),
  );
  const { video: a } = attach("a");
  const { video: b } = attach("b");
  a.duration = 1;
  await frame();
  await frame();
  await frame(1.1);
  expect(a.currentTime).toBe(1);
  expect(a.paused).toBe(true);
  expect(b.paused).toBe(false);
  await frame(4);
  expect([a.currentTime, b.currentTime]).toEqual([0, 0]);
  expect(a.paused && b.paused).toBe(true);
  a.finishSeek();
  b.finishSeek();
  await frame();
  await frame();
  expect(a.paused || b.paused).toBe(false);
});

it("replaces sources at zero, retains pause and speed, and releases media on disposal", async () => {
  controller.configure(new Map([["a", pane("a")]]));
  const { video } = attach("a");
  await frame();
  await frame();
  await frame(0.4);
  controller.pause();
  controller.setRate(0.5);
  controller.configure(new Map([["a", pane("a", "/new.mp4")]]));
  expect(controller.state.get()).toMatchObject({
    time: 0,
    paused: true,
    rate: 0.5,
  });
  controller.dispose();
  expect(video.paused).toBe(true);
  expect(callbacks.size).toBe(0);
});

it("lets the common clock finish when a decoder ends slightly early", async () => {
  controller.configure(new Map([["a", pane("a")]]));
  const { video } = attach("a");
  video.duration = 2;
  controller.toggleLoop();
  await frame();
  await frame();
  await frame(1.99);
  video.ended = true;
  video.paused = true;
  const play = vi.spyOn(video, "play");
  await frame();
  expect(play).not.toHaveBeenCalled();
  await frame(0.02);
  expect(controller.state.get()).toMatchObject({ time: 2, paused: true });
});

it("freezes immediately on tab hiding and disables stepping for mixed frame rates", async () => {
  const a = pane("a"),
    b = pane("b");
  b.props.fps = 30;
  const panes = new Map([
    ["a", a],
    ["b", b],
  ]);
  controller.configure(panes);
  attach("a");
  attach("b");
  await frame();
  await frame();
  await frame(0.2);
  expect(controller.state.get().fps).toBeNull();
  vi.stubGlobal("document", { hidden: true });
  controller.configure(panes);
  expect(videos.every((v) => v.paused)).toBe(true);
  const time = controller.state.get().time;
  await frame(10);
  expect(controller.state.get().time).toBe(time);
});
