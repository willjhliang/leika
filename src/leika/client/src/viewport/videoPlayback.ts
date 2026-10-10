import { createStore } from "../store";
import type { ViewportVideoPane, ViewportState } from "./ViewportState";

export interface PlaybackState {
  time: number;
  duration: number;
  paused: boolean;
  rate: number;
  loop: boolean;
  fps: number | null;
  buffering: boolean;
  error: boolean;
}

type Member = {
  video: HTMLVideoElement;
  visible: boolean;
  automaticPauses: number;
  automaticPlays: number;
  seeking: boolean;
  rate: number;
  starting: boolean;
  cleanup: () => void;
};

/** One clock for either a single player or a named group. All state is local to
 * this viewer. DOM media elements are adapters; controls never own the clock. */
export class VideoPlayback {
  readonly state = createStore<PlaybackState>({
    time: 0,
    duration: 0,
    paused: true,
    rate: 1,
    loop: true,
    fps: null,
    buffering: false,
    error: false,
  });
  private expected = new Map<string, ViewportVideoPane>();
  private members = new Map<string, Member>();
  private initialized = false;
  private runningSince: number | null = null;
  private frame: number | null = null;
  private disposed = false;

  configure(panes: Map<string, ViewportVideoPane>): void {
    const first = panes.values().next().value as ViewportVideoPane | undefined;
    const sourceChanged = [...panes].some(([id, pane]) => {
      const old = this.expected.get(id);
      return old !== undefined && old.props._url !== pane.props._url;
    });
    if (first && !this.initialized) {
      this.state.set({ paused: !first.props.autoplay, loop: first.props.loop });
      this.initialized = true;
    }
    this.expected = panes;
    if (document.hidden) this.suspend();
    const fps = first?.props.fps ?? null;
    this.state.set({
      fps: [...panes.values()].every((p) => p.props.fps === fps) ? fps : null,
    });
    if (sourceChanged) this.seek(0);
    this.wake();
  }

  attach(
    id: string,
    video: HTMLVideoElement,
  ): { visible: (value: boolean) => void; remove: () => void } {
    const old = this.members.get(id);
    old?.cleanup();
    const member: Member = {
      video,
      visible: false,
      automaticPauses: 0,
      automaticPlays: 0,
      seeking: false,
      rate: video.playbackRate,
      starting: false,
      cleanup: () => {},
    };
    const onPause = () => {
      if (member.automaticPauses > 0) member.automaticPauses--;
      else if (!video.ended) this.pause();
      this.wake();
    };
    const onPlay = () => {
      if (member.automaticPlays > 0) member.automaticPlays--;
      else this.play();
      this.wake();
    };
    const onSeek = () => {
      if (!member.seeking) this.seek(video.currentTime, video);
      this.wake();
    };
    const onSeeked = () => {
      member.seeking = false;
      this.wake();
    };
    const onRate = () => {
      if (video.playbackRate !== member.rate) this.setRate(video.playbackRate);
    };
    const events: [string, () => void][] = [
      ["pause", onPause],
      ["play", onPlay],
      ["seeking", onSeek],
      ["seeked", onSeeked],
      ["ratechange", onRate],
      ...[
        "loadedmetadata",
        "loadeddata",
        "canplay",
        "waiting",
        "ended",
        "error",
        "durationchange",
      ].map((event) => [event, this.wake] as [string, () => void]),
    ];
    events.forEach(([event, callback]) =>
      video.addEventListener(event, callback),
    );
    const remove = () => {
      events.forEach(([event, callback]) =>
        video.removeEventListener(event, callback),
      );
      video.pause();
      if (this.members.get(id) === member) this.members.delete(id);
      this.wake();
    };
    member.cleanup = remove;
    this.members.set(id, member);
    this.applyRate(member);
    this.wake();
    return {
      visible: (value) => {
        if (value === member.visible) return;
        member.visible = value;
        if (value) this.align(member, this.now());
        else this.stop(member);
        this.wake();
      },
      remove,
    };
  }

  private suspend(): void {
    this.freeze();
    this.members.forEach((m) => this.stop(m));
  }

  play = (): void => {
    if (this.state.get().time >= this.state.get().duration) this.seek(0);
    this.state.set({ paused: false });
    this.wake();
  };
  pause = (): void => {
    this.freeze();
    this.state.set({ paused: true, buffering: false });
    this.members.forEach((m) => this.stop(m));
    this.wake();
  };
  seek = (time: number, origin?: HTMLVideoElement): void => {
    this.freeze();
    const duration = this.state.get().duration;
    this.state.set({ time: Math.max(0, Math.min(time, duration || time)) });
    this.members.forEach((m) => {
      if (m.video === origin) return;
      this.stop(m);
      this.align(m, this.state.get().time);
    });
    this.wake();
  };
  step = (direction: number): void => {
    const { fps, time } = this.state.get();
    if (fps === null) return;
    this.pause();
    this.seek((Math.round(time * fps) + direction) / fps);
  };
  setRate = (rate: number): void => {
    if (!Number.isFinite(rate) || rate <= 0) return;
    this.freeze();
    this.state.set({ rate });
    this.members.forEach((m) => this.applyRate(m));
    this.wake();
  };
  toggleLoop = (): void => {
    this.state.set((s) => ({ loop: !s.loop }));
  };

  private now(): number {
    const { time, rate } = this.state.get();
    return (
      time +
      (this.runningSince === null
        ? 0
        : ((performance.now() - this.runningSince) / 1000) * rate)
    );
  }
  private freeze(): void {
    this.state.set({ time: this.now() });
    this.runningSince = null;
  }
  private stop(member: Member): void {
    if (!member.video.paused) {
      member.automaticPauses++;
      member.video.pause();
    }
  }
  private align(member: Member, time: number): void {
    const video = member.video;
    if (
      video.readyState < 1 ||
      !Number.isFinite(video.duration) ||
      video.seeking
    )
      return;
    const target = Math.min(time, video.duration);
    if (Math.abs(video.currentTime - target) > 0.0001) {
      member.seeking = true;
      video.currentTime = target;
    }
  }
  private applyRate(member: Member): void {
    const rate = this.state.get().rate;
    member.rate = rate;
    if (member.video.playbackRate !== rate) member.video.playbackRate = rate;
  }
  private wake = (): void => {
    if (this.frame === null && !this.disposed)
      this.frame = requestAnimationFrame(this.tick);
  };
  private tick = (): void => {
    this.frame = null;
    const active: Member[] = [];
    let missing = false;
    let duration = 0;
    let error = false;
    for (const [id, pane] of this.expected) {
      const member = this.members.get(id);
      if (member && Number.isFinite(member.video.duration))
        duration = Math.max(duration, member.video.duration);
      if (!pane.props.visible) {
        if (member) this.stop(member);
        continue;
      }
      if (!member || pane.props.loading || pane.refreshPending !== undefined) {
        missing = true;
        continue;
      }
      if (!member.visible || document.hidden) {
        this.stop(member);
        continue;
      }
      error ||= member.video.error !== null;
      active.push(member);
    }
    this.state.set({ duration, error });
    let time = this.now();
    if (duration > 0 && time >= duration) {
      if (this.state.get().loop && !this.state.get().paused) this.seek(0);
      else {
        this.pause();
        this.state.set({ time: duration });
      }
      time = this.state.get().time;
    }
    const blocked =
      missing ||
      error ||
      active.some((m) => m.video.seeking || m.video.readyState < 3);
    const paused = this.state.get().paused;
    if (paused || blocked || active.length === 0) {
      this.freeze();
      // A single visible decoder already waits on its own seek/buffer. Leave
      // its native play promise intact; multiple decoders need a pause barrier.
      if (paused || active.length !== 1 || missing || error)
        this.members.forEach((m) => this.stop(m));
      // Metadata can arrive after a seek; align newly loaded members before playing.
      active.forEach((m) => this.align(m, this.state.get().time));
      this.state.set({
        buffering: !paused && (blocked || active.length === 0),
      });
      return;
    }
    // Correct drift through the same seek barrier used by the timeline.
    if (
      active.some(
        (m) =>
          Math.abs(m.video.currentTime - Math.min(time, m.video.duration)) >
          0.08,
      )
    ) {
      this.seek(time);
      this.state.set({ buffering: true });
      return;
    }
    let starting = false;
    for (const member of active) {
      this.applyRate(member);
      // A decoder can finish a few milliseconds before the shared clock.
      // Calling play() on it would implicitly seek to zero and restart the group.
      if (time >= member.video.duration || member.video.ended) {
        this.stop(member);
        continue;
      }
      if (member.video.paused && !member.starting) {
        member.starting = true;
        member.automaticPlays++;
        void member.video
          .play()
          .catch((error: unknown) => {
            // AbortError is the expected result of a pause/seek during startup.
            if (!(error instanceof DOMException && error.name === "AbortError"))
              this.pause();
          })
          .finally(() => {
            member.starting = false;
            this.wake();
          });
      }
      starting ||= member.starting;
    }
    if (!starting && this.runningSince === null)
      this.runningSince = performance.now();
    if (this.runningSince !== null) {
      this.state.set({ time: this.now(), buffering: false });
      this.runningSince = performance.now();
    } else this.state.set({ buffering: true });
    this.wake();
  };

  dispose(): void {
    this.disposed = true;
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = null;
    this.members.forEach((m) => m.cleanup());
    this.members.clear();
  }
}

export function videoPlaybackKey(
  pane: ViewportVideoPane,
  pageId: string,
): string {
  return pane.props.sync_group === null
    ? JSON.stringify(["pane", pageId, pane.paneId])
    : groupPlaybackKey(pane.props.sync_group);
}
export function groupPlaybackKey(group: string): string {
  return JSON.stringify(["group", group]);
}

/** Bounded by the live pane and mounted GUI counts. A dock view can detach
 * without destroying a controller that still owns panes. */
export class VideoPlaybackRegistry {
  private groups = new Map<
    string,
    { playback: VideoPlayback; references: number; expected: boolean }
  >();
  get(key: string): VideoPlayback {
    let entry = this.groups.get(key);
    if (!entry) {
      entry = { playback: new VideoPlayback(), references: 0, expected: false };
      this.groups.set(key, entry);
    }
    return entry.playback;
  }
  retain(key: string): () => void {
    this.get(key);
    const entry = this.groups.get(key)!;
    entry.references++;
    return () => {
      entry.references--;
      queueMicrotask(() => this.prune());
    };
  }
  reconcile(state: ViewportState): void {
    const page =
      state.displayPageId === null
        ? undefined
        : state.pages[state.displayPageId];
    const groups = new Map<string, Map<string, ViewportVideoPane>>();
    if (page && state.transitionPage === null) {
      for (const pane of Object.values(page.panes)) {
        if (pane.kind !== "video") continue;
        const key = videoPlaybackKey(pane, page.pageId);
        let members = groups.get(key);
        if (!members) {
          members = new Map();
          groups.set(key, members);
        }
        members.set(pane.paneId, pane);
        this.get(key);
      }
    }
    for (const [key, entry] of this.groups) {
      const members = groups.get(key);
      entry.expected = members !== undefined;
      entry.playback.configure(members ?? new Map());
    }
    queueMicrotask(() => this.prune());
  }
  private prune(): void {
    for (const [key, entry] of this.groups) {
      if (entry.references === 0 && !entry.expected) {
        entry.playback.dispose();
        this.groups.delete(key);
      }
    }
  }
  dispose(): void {
    this.groups.forEach((entry) => entry.playback.dispose());
    this.groups.clear();
  }
}
