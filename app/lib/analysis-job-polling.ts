// Pure, unit-testable decision helpers for the job status page's
// polling loop (app/analysis/jobs/[id]/page.tsx) — kept separate from
// that page's React wiring (a `setTimeout` chain plus a
// `visibilitychange` listener) so the actual scheduling/backoff logic
// can be tested without a React component-rendering library, which
// this project doesn't have (same reasoning as every other
// app/lib/*.ts file — see app/lib/analysis-history.ts's module
// comment).

import { isTerminalJobStatus } from "./analysis-jobs";

/** Default interval (ms) between polls while a job is queued/running
 * and no error has occurred — docs/40 "6"'s "初期値の目安は5秒程度". */
export const DEFAULT_POLL_INTERVAL_MS = 5_000;

/** Upper bound for the exponential backoff below — never wait longer
 * than this between polls even after many consecutive failures. */
export const MAX_POLL_INTERVAL_MS = 60_000;

/** HTTP status codes that mean polling should stop entirely (not just
 * back off) — docs/40 "6"'s "401/403ではポーリングを停止し適切に案内"/
 * "404では存在しないジョブとして扱う". */
export function shouldStopPollingForStatusCode(httpStatus: number): boolean {
  return httpStatus === 401 || httpStatus === 403 || httpStatus === 404;
}

/** Whether polling should continue given the job's current `status` —
 * false once a terminal status (completed/partial/failed) is reached. */
export function shouldContinuePollingForJobStatus(status: string): boolean {
  return !isTerminalJobStatus(status);
}

/**
 * Computes the delay (ms) before the next poll attempt, given how
 * many consecutive network/transport failures have just occurred (0
 * when the previous poll succeeded, regardless of job status).
 * Exponential backoff, capped at MAX_POLL_INTERVAL_MS — this is for
 * genuine network-level failures (fetch() rejecting, or a response
 * this module doesn't otherwise recognize), not for a healthy
 * queued/running job, which always polls at `baseIntervalMs`.
 */
export function computeNextPollDelayMs(
  consecutiveFailureCount: number,
  baseIntervalMs: number = DEFAULT_POLL_INTERVAL_MS,
): number {
  if (consecutiveFailureCount <= 0) return baseIntervalMs;
  const backoff = baseIntervalMs * 2 ** Math.min(consecutiveFailureCount, 5);
  return Math.min(backoff, MAX_POLL_INTERVAL_MS);
}
