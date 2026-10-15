import { describe, expect, it } from "vitest";
import {
  DEFAULT_POLL_INTERVAL_MS,
  MAX_POLL_INTERVAL_MS,
  computeNextPollDelayMs,
  shouldContinuePollingForJobStatus,
  shouldStopPollingForStatusCode,
} from "./analysis-job-polling";

describe("shouldStopPollingForStatusCode", () => {
  it("is true for 401/403/404", () => {
    expect(shouldStopPollingForStatusCode(401)).toBe(true);
    expect(shouldStopPollingForStatusCode(403)).toBe(true);
    expect(shouldStopPollingForStatusCode(404)).toBe(true);
  });

  it("is false for 200/500/other codes", () => {
    expect(shouldStopPollingForStatusCode(200)).toBe(false);
    expect(shouldStopPollingForStatusCode(500)).toBe(false);
    expect(shouldStopPollingForStatusCode(503)).toBe(false);
  });
});

describe("shouldContinuePollingForJobStatus", () => {
  it("is true for queued/running", () => {
    expect(shouldContinuePollingForJobStatus("queued")).toBe(true);
    expect(shouldContinuePollingForJobStatus("running")).toBe(true);
  });

  it("is false for completed/partial/failed", () => {
    expect(shouldContinuePollingForJobStatus("completed")).toBe(false);
    expect(shouldContinuePollingForJobStatus("partial")).toBe(false);
    expect(shouldContinuePollingForJobStatus("failed")).toBe(false);
  });
});

describe("computeNextPollDelayMs", () => {
  it("returns the base interval when there have been no failures", () => {
    expect(computeNextPollDelayMs(0)).toBe(DEFAULT_POLL_INTERVAL_MS);
    expect(computeNextPollDelayMs(-1)).toBe(DEFAULT_POLL_INTERVAL_MS);
  });

  it("doubles the delay for each consecutive failure", () => {
    expect(computeNextPollDelayMs(1)).toBe(DEFAULT_POLL_INTERVAL_MS * 2);
    expect(computeNextPollDelayMs(2)).toBe(DEFAULT_POLL_INTERVAL_MS * 4);
    expect(computeNextPollDelayMs(3)).toBe(DEFAULT_POLL_INTERVAL_MS * 8);
  });

  it("never exceeds MAX_POLL_INTERVAL_MS, even after many failures", () => {
    expect(computeNextPollDelayMs(20)).toBe(MAX_POLL_INTERVAL_MS);
  });

  it("respects a custom base interval", () => {
    expect(computeNextPollDelayMs(0, 1_000)).toBe(1_000);
    expect(computeNextPollDelayMs(1, 1_000)).toBe(2_000);
  });
});
