import { expect, test, vi } from "vitest";

import { LatestBlobTextReader } from "./latestBlobTextReader";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, reject, resolve };
}

function blobWithText(text: () => Promise<string>): Blob {
  return { size: 1, text } as unknown as Blob;
}

test("rapid replacements decode only the active and newest Blobs", async () => {
  const reader = new LatestBlobTextReader();
  const first = deferred<string>();
  const last = deferred<string>();
  const firstText = vi.fn(() => first.promise);
  const skippedText = vi.fn(() => Promise.resolve("skipped"));
  const lastText = vi.fn(() => last.promise);
  const firstResult = vi.fn();
  const skippedResult = vi.fn();
  const lastResult = vi.fn();

  reader.request(blobWithText(firstText), firstResult);
  reader.request(blobWithText(skippedText), skippedResult);
  reader.request(blobWithText(lastText), lastResult);

  expect(firstText).toHaveBeenCalledOnce();
  expect(skippedText).not.toHaveBeenCalled();
  expect(lastText).not.toHaveBeenCalled();

  first.resolve("stale");
  await first.promise;
  await Promise.resolve();
  expect(firstResult).not.toHaveBeenCalled();
  expect(skippedText).not.toHaveBeenCalled();
  expect(lastText).toHaveBeenCalledOnce();

  last.resolve("current");
  await last.promise;
  await Promise.resolve();
  expect(lastResult).toHaveBeenCalledWith("current");
  expect(skippedResult).not.toHaveBeenCalled();
});

test("clear releases pending work and suppresses an active result", async () => {
  const reader = new LatestBlobTextReader();
  const active = deferred<string>();
  const activeResult = vi.fn();
  const pendingText = vi.fn(() => Promise.resolve("pending"));

  reader.request(
    blobWithText(() => active.promise),
    activeResult,
  );
  reader.request(blobWithText(pendingText), vi.fn());
  reader.clear();
  active.resolve("stale");
  await active.promise;
  await Promise.resolve();

  expect(activeResult).not.toHaveBeenCalled();
  expect(pendingText).not.toHaveBeenCalled();
});

test("a repeated request for the active Blob reuses its conversion", async () => {
  const reader = new LatestBlobTextReader();
  const decoded = deferred<string>();
  const text = vi.fn(() => decoded.promise);
  const blob = blobWithText(text);
  const staleResult = vi.fn();
  const currentResult = vi.fn();

  const cancelStale = reader.request(blob, staleResult);
  cancelStale();
  reader.request(blob, currentResult);
  decoded.resolve("once");
  await decoded.promise;
  await Promise.resolve();

  expect(text).toHaveBeenCalledOnce();
  expect(staleResult).not.toHaveBeenCalled();
  expect(currentResult).toHaveBeenCalledWith("once");
});

test("cancel and read failures cannot publish stale content", async () => {
  const reader = new LatestBlobTextReader();
  const rejected = deferred<string>();
  const rejectedResult = vi.fn();
  const cancel = reader.request(
    blobWithText(() => rejected.promise),
    rejectedResult,
  );
  cancel();
  rejected.reject(new Error("unreadable"));
  await rejected.promise.catch(() => undefined);
  await Promise.resolve();
  expect(rejectedResult).not.toHaveBeenCalled();

  const failedResult = vi.fn();
  reader.request(
    blobWithText(() => Promise.reject(new Error("unreadable"))),
    failedResult,
  );
  await Promise.resolve();
  await Promise.resolve();
  expect(failedResult).toHaveBeenCalledWith("");
});
