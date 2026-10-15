// A small, fully unit-testable state machine owning every concurrency
// decision for the job status page's polling loop
// (app/analysis/jobs/[id]/page.tsx) — split out of that component (a
// review found the original inline setTimeout chain could still issue
// a second, overlapping request when `visibilitychange` fired while a
// poll was already in flight) so the actual scheduling/concurrency
// logic can be exercised with fake dependencies (a controllable fake
// fetch, fake timers, a fake visibility flag) instead of needing a
// real browser DOM, which this project's vitest run doesn't have.
//
// Guarantees this module provides (see createAnalysisJobPollController()):
// - never more than one `fetchStatus()` call in flight at a time —
//   `handleVisibilityChange(true)` while a fetch is already running
//   defers to a "run again immediately once this one finishes" flag
//   instead of starting a second request.
// - a stale response can never overwrite a newer one — each attempt
//   is tagged with a monotonically increasing version number; the
//   result is only applied if that version is still current (defense
//   in depth on top of the in-flight guard above, which already rules
//   out two requests running concurrently within one controller
//   instance).
// - no state update after stop() — every continuation point checks a
//   `cancelled` flag first.
// - no further polling after a 401/403/404, or after the job reaches
//   a terminal status (completed/partial/failed) — see
//   shouldStopPollingForStatusCode()/shouldContinuePollingForJobStatus()
//   in app/lib/analysis-job-polling.ts.
// - the in-flight request's AbortSignal is aborted on stop() (e.g.
//   component unmount), so a request already in flight is actually
//   cancelled at the network layer, not just ignored once it resolves.

import {
  resolveAnalysisJobStatusOutcome,
  type AnalysisJobStatusViewState,
} from "./analysis-jobs";
import {
  computeNextPollDelayMs,
  shouldContinuePollingForJobStatus,
  shouldStopPollingForStatusCode,
} from "./analysis-job-polling";

export interface AnalysisJobPollControllerDeps {
  /** Performs the actual GET /api/analysis-jobs/{id} fetch. Must
   * resolve to `null` (not throw/reject) on a network-level failure —
   * mirrors every other `fetch(...).catch(() => null)` call site in
   * this codebase. Receives an AbortSignal that the controller aborts
   * on stop(). */
  fetchStatus: (signal: AbortSignal) => Promise<Response | null>;
  /** Called with each resolved view state, in order, only while the
   * controller is neither stopped nor cancelled, and only for the
   * most recent in-flight request (see the version-check guarantee
   * above). */
  onOutcome: (outcome: AnalysisJobStatusViewState) => void;
  /** Whether the tab is currently visible — the controller never
   * starts a fetch while this returns false. */
  isVisible: () => boolean;
  setTimeout: (callback: () => void, delayMs: number) => unknown;
  clearTimeout: (handle: unknown) => void;
}

export interface AnalysisJobPollController {
  /** Starts the first poll attempt immediately (subject to
   * `isVisible()`, same as every later attempt). */
  start: () => void;
  /** Stops polling permanently: cancels any scheduled timer, aborts
   * an in-flight request, and suppresses every future state update —
   * call from the component's effect cleanup (unmount, or `id`
   * changing). */
  stop: () => void;
  /** Call from a `visibilitychange` listener with the tab's new
   * visibility. Becoming visible while a request is already in
   * flight does NOT start a second one — it only arms an immediate
   * re-poll for right after the current one finishes. */
  handleVisibilityChange: (isVisible: boolean) => void;
}

export function createAnalysisJobPollController(
  deps: AnalysisJobPollControllerDeps,
): AnalysisJobPollController {
  let cancelled = false;
  let stopped = false;
  let inFlight = false;
  let pendingImmediatePoll = false;
  let consecutiveFailures = 0;
  let requestVersion = 0;
  let timeoutHandle: unknown = null;
  let currentAbortController: AbortController | null = null;

  function clearScheduled() {
    if (timeoutHandle !== null) {
      deps.clearTimeout(timeoutHandle);
      timeoutHandle = null;
    }
  }

  function scheduleNext(delayMs: number) {
    if (cancelled || stopped) return;
    clearScheduled();
    timeoutHandle = deps.setTimeout(() => {
      void poll();
    }, delayMs);
  }

  function afterAttemptSettled() {
    inFlight = false;
    currentAbortController = null;
    if (cancelled || stopped) return;

    if (pendingImmediatePoll && deps.isVisible()) {
      pendingImmediatePoll = false;
      void poll();
      return;
    }
    scheduleNext(computeNextPollDelayMs(consecutiveFailures));
  }

  async function poll(): Promise<void> {
    if (cancelled || stopped) return;
    if (inFlight) return; // never start a second concurrent request
    if (!deps.isVisible()) return; // visibilitychange resumes this, nothing scheduled here

    inFlight = true;
    const myVersion = ++requestVersion;
    const abortController = new AbortController();
    currentAbortController = abortController;

    try {
      let response: Response | null;
      try {
        response = await deps.fetchStatus(abortController.signal);
      } catch {
        response = null;
      }

      // A newer attempt (or stop()) superseded this one while the
      // fetch was in flight — never act on a stale result.
      if (cancelled || stopped || myVersion !== requestVersion) return;

      if (!response) {
        consecutiveFailures += 1;
        return;
      }

      consecutiveFailures = 0;
      const outcome = await resolveAnalysisJobStatusOutcome(response);
      if (cancelled || stopped || myVersion !== requestVersion) return;

      deps.onOutcome(outcome);

      const statusIsTerminal =
        outcome.kind === "status" && !shouldContinuePollingForJobStatus(outcome.job.status);
      if (shouldStopPollingForStatusCode(response.status) || statusIsTerminal) {
        stopped = true;
      }
    } finally {
      afterAttemptSettled();
    }
  }

  return {
    start() {
      void poll();
    },
    stop() {
      cancelled = true;
      clearScheduled();
      currentAbortController?.abort();
    },
    handleVisibilityChange(isVisible: boolean) {
      if (cancelled || stopped) return;
      if (!isVisible) return;
      if (inFlight) {
        // A request is already running — don't start a second one;
        // run again as soon as this one settles instead.
        pendingImmediatePoll = true;
        return;
      }
      clearScheduled();
      void poll();
    },
  };
}
