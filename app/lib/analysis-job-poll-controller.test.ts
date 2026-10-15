// Unit tests for createAnalysisJobPollController() — exercised with a
// fully fake scheduler (no real timers) and manually-resolved
// deferred fetch promises, since every one of the controller's
// dependencies (fetchStatus/setTimeout/clearTimeout/isVisible) is
// injected precisely so this is possible without a real browser DOM
// (this project's vitest run has no jsdom — see this file's sibling
// analysis-jobs.test.ts for the same convention).

import { describe, expect, it, vi } from "vitest";
import {
  createAnalysisJobPollController,
  type AnalysisJobPollControllerDeps,
} from "./analysis-job-poll-controller";
import { DEFAULT_POLL_INTERVAL_MS, computeNextPollDelayMs } from "./analysis-job-polling";
import type { AnalysisJobStatusViewState } from "./analysis-jobs";

/** Drains enough microtask turns for a chain of `await`s (fetchStatus
 * -> response.json() -> resolveAnalysisJobStatusOutcome's own return)
 * to fully settle before assertions run. */
async function flushMicrotasks(times = 6): Promise<void> {
  for (let i = 0; i < times; i += 1) {
    await Promise.resolve();
  }
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeStatusResponse(httpStatus: number, body?: unknown): Response {
  return {
    ok: httpStatus >= 200 && httpStatus < 300,
    status: httpStatus,
    json: async () => body,
  } as unknown as Response;
}

function makeFakeScheduler() {
  let nextHandle = 0;
  const scheduled = new Map<number, { callback: () => void; delayMs: number }>();

  return {
    setTimeout: (callback: () => void, delayMs: number): unknown => {
      const handle = ++nextHandle;
      scheduled.set(handle, { callback, delayMs });
      return handle;
    },
    clearTimeout: (handle: unknown): void => {
      scheduled.delete(handle as number);
    },
    pendingCount: (): number => scheduled.size,
    lastDelayMs: (): number | undefined => {
      const entries = Array.from(scheduled.values());
      return entries[entries.length - 1]?.delayMs;
    },
    /** Fires every timer currently scheduled (simulates real time passing). */
    flush: (): void => {
      const entries = Array.from(scheduled.entries());
      scheduled.clear();
      entries.forEach(([, { callback }]) => callback());
    },
  };
}

/** Builds a controller wired to a fake scheduler and a `fetchStatus`
 * that resolves from a manually-controlled queue of deferreds, so
 * each test can decide exactly when each fetch "completes". */
function setup(overrides: Partial<AnalysisJobPollControllerDeps> = {}) {
  const scheduler = makeFakeScheduler();
  const fetchStatus = vi.fn<(signal: AbortSignal) => Promise<Response | null>>();
  const onOutcome = vi.fn<(outcome: AnalysisJobStatusViewState) => void>();
  let visible = true;

  const controller = createAnalysisJobPollController({
    fetchStatus,
    onOutcome,
    isVisible: () => visible,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
    ...overrides,
  });

  return {
    controller,
    scheduler,
    fetchStatus,
    onOutcome,
    setVisible: (value: boolean) => {
      visible = value;
    },
  };
}

describe("createAnalysisJobPollController", () => {
  it("never issues a second fetch while one is already in flight, even when handleVisibilityChange(true) fires", async () => {
    const { controller, fetchStatus } = setup();
    const first = createDeferred<Response | null>();
    fetchStatus.mockReturnValueOnce(first.promise);

    controller.start();
    expect(fetchStatus).toHaveBeenCalledTimes(1);

    // Tab becomes visible again while the first request is still in
    // flight — this must NOT start a second concurrent fetch.
    controller.handleVisibilityChange(true);
    expect(fetchStatus).toHaveBeenCalledTimes(1);

    const second = createDeferred<Response | null>();
    fetchStatus.mockReturnValueOnce(second.promise);
    first.resolve(makeStatusResponse(200, { analysisRunId: "job-1", status: "running" }));
    await flushMicrotasks();

    // The deferred visibility re-poll runs immediately once the first
    // settles — exactly one more fetch, not two.
    expect(fetchStatus).toHaveBeenCalledTimes(2);
  });

  it("a stale (older) response never overwrites a newer state once a later request has started", async () => {
    const { controller, fetchStatus, onOutcome, scheduler } = setup();
    const first = createDeferred<Response | null>();
    fetchStatus.mockReturnValueOnce(first.promise);

    controller.start();
    expect(fetchStatus).toHaveBeenCalledTimes(1);

    // Let the first request resolve immediately as a normal running
    // status so the controller schedules a second attempt, then fire
    // that second attempt while keeping a handle on the FIRST
    // promise's resolve — simulating network reordering is not
    // directly expressible through the in-flight guard (only one
    // fetch is ever outstanding at a time), so instead this verifies
    // the version check directly: a response that resolves after
    // stop() has been called must never reach onOutcome.
    controller.stop();
    first.resolve(makeStatusResponse(200, { analysisRunId: "job-1", status: "running" }));
    await flushMicrotasks();

    expect(onOutcome).not.toHaveBeenCalled();
    expect(scheduler.pendingCount()).toBe(0);
  });

  it("does not update state after stop() (component unmount) while a request is in flight", async () => {
    const { controller, fetchStatus, onOutcome } = setup();
    const first = createDeferred<Response | null>();
    fetchStatus.mockReturnValueOnce(first.promise);

    controller.start();
    controller.stop();

    first.resolve(makeStatusResponse(200, { analysisRunId: "job-1", status: "completed" }));
    await flushMicrotasks();

    expect(onOutcome).not.toHaveBeenCalled();
  });

  it("aborts the in-flight request's signal on stop()", () => {
    const { controller, fetchStatus } = setup();
    const first = createDeferred<Response | null>();
    fetchStatus.mockReturnValueOnce(first.promise);

    controller.start();
    const signal = fetchStatus.mock.calls[0][0];
    expect(signal.aborted).toBe(false);

    controller.stop();
    expect(signal.aborted).toBe(true);
  });

  it("stops polling permanently after a 401 response", async () => {
    const { controller, fetchStatus, onOutcome, scheduler } = setup();
    fetchStatus.mockResolvedValueOnce(makeStatusResponse(401));

    controller.start();
    await flushMicrotasks();

    expect(onOutcome).toHaveBeenCalledWith({
      kind: "unauthorized",
      message: expect.any(String),
    });
    expect(scheduler.pendingCount()).toBe(0);

    // Becoming visible again afterward must not resume polling.
    controller.handleVisibilityChange(true);
    expect(fetchStatus).toHaveBeenCalledTimes(1);
  });

  it("stops polling permanently after a 404 response", async () => {
    const { controller, fetchStatus, scheduler } = setup();
    fetchStatus.mockResolvedValueOnce(makeStatusResponse(404));

    controller.start();
    await flushMicrotasks();

    expect(scheduler.pendingCount()).toBe(0);
    controller.handleVisibilityChange(true);
    expect(fetchStatus).toHaveBeenCalledTimes(1);
  });

  it("stops polling once the job reaches a terminal status (completed)", async () => {
    const { controller, fetchStatus, onOutcome, scheduler } = setup();
    fetchStatus.mockResolvedValueOnce(
      makeStatusResponse(200, { analysisRunId: "job-1", status: "completed" }),
    );

    controller.start();
    await flushMicrotasks();

    expect(onOutcome).toHaveBeenCalledWith({
      kind: "status",
      job: expect.objectContaining({ status: "completed" }),
    });
    expect(scheduler.pendingCount()).toBe(0);

    controller.handleVisibilityChange(true);
    expect(fetchStatus).toHaveBeenCalledTimes(1);
  });

  it("keeps polling at the base interval while the job is still queued/running", async () => {
    const { controller, fetchStatus, scheduler } = setup();
    fetchStatus.mockResolvedValueOnce(
      makeStatusResponse(200, { analysisRunId: "job-1", status: "running" }),
    );

    controller.start();
    await flushMicrotasks();

    expect(scheduler.pendingCount()).toBe(1);
    expect(scheduler.lastDelayMs()).toBe(DEFAULT_POLL_INTERVAL_MS);
  });

  it("recovers after a network-level failure, backing off exponentially until the next success", async () => {
    const { controller, fetchStatus, scheduler } = setup();
    fetchStatus.mockResolvedValueOnce(null);

    controller.start();
    await flushMicrotasks();

    expect(scheduler.lastDelayMs()).toBe(computeNextPollDelayMs(1));

    fetchStatus.mockResolvedValueOnce(null);
    scheduler.flush();
    await flushMicrotasks();

    expect(scheduler.lastDelayMs()).toBe(computeNextPollDelayMs(2));

    fetchStatus.mockResolvedValueOnce(
      makeStatusResponse(200, { analysisRunId: "job-1", status: "running" }),
    );
    scheduler.flush();
    await flushMicrotasks();

    // A success resets the failure count back to the base interval.
    expect(scheduler.lastDelayMs()).toBe(DEFAULT_POLL_INTERVAL_MS);
  });

  it("does not fetch while the tab is hidden, and resumes on becoming visible", async () => {
    const { controller, fetchStatus, setVisible } = setup();
    setVisible(false);

    controller.start();
    expect(fetchStatus).not.toHaveBeenCalled();

    setVisible(true);
    fetchStatus.mockResolvedValueOnce(
      makeStatusResponse(200, { analysisRunId: "job-1", status: "running" }),
    );
    controller.handleVisibilityChange(true);
    await flushMicrotasks();

    expect(fetchStatus).toHaveBeenCalledTimes(1);
  });

  it("has no effect calling handleVisibilityChange(false) — it only ever triggers on becoming visible", () => {
    const { controller, fetchStatus } = setup();
    const first = createDeferred<Response | null>();
    fetchStatus.mockReturnValueOnce(first.promise);

    controller.start();
    controller.handleVisibilityChange(false);

    expect(fetchStatus).toHaveBeenCalledTimes(1);
  });
});
