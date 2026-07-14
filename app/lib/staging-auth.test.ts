import { describe, expect, it } from "vitest";
import { hashAccessCode, sanitizeNextPath } from "./staging-auth";

describe("hashAccessCode", () => {
  it("is deterministic for the same input", () => {
    expect(hashAccessCode("secret")).toBe(hashAccessCode("secret"));
  });

  it("differs for different inputs", () => {
    expect(hashAccessCode("secret")).not.toBe(hashAccessCode("other"));
  });

  it("never returns the plaintext code itself", () => {
    expect(hashAccessCode("secret")).not.toBe("secret");
  });
});

describe("sanitizeNextPath", () => {
  it("returns the value when it is a relative path", () => {
    expect(sanitizeNextPath("/analyze")).toBe("/analyze");
  });

  it("defaults to / when the value is missing", () => {
    expect(sanitizeNextPath(null)).toBe("/");
    expect(sanitizeNextPath(undefined)).toBe("/");
    expect(sanitizeNextPath("")).toBe("/");
  });

  it("rejects protocol-relative URLs (open redirect)", () => {
    expect(sanitizeNextPath("//evil.com")).toBe("/");
  });

  it("rejects absolute URLs", () => {
    expect(sanitizeNextPath("https://evil.com")).toBe("/");
  });

  it("rejects values that don't start with a slash", () => {
    expect(sanitizeNextPath("evil.com")).toBe("/");
  });
});
