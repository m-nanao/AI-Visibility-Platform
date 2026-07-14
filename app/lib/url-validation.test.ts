import { describe, expect, it } from "vitest";
import { MAX_URLS, validateUrlsInput } from "./url-validation";

describe("validateUrlsInput", () => {
  it("returns no urls and no errors for empty input", () => {
    const result = validateUrlsInput("");
    expect(result).toEqual({ urls: [], errors: [] });
  });

  it("returns no urls and no errors for whitespace-only input", () => {
    const result = validateUrlsInput("   \n\n   ");
    expect(result).toEqual({ urls: [], errors: [] });
  });

  it("accepts a single valid url", () => {
    const result = validateUrlsInput("https://example.com/a");
    expect(result).toEqual({ urls: ["https://example.com/a"], errors: [] });
  });

  it("accepts exactly MAX_URLS urls", () => {
    const urls = Array.from({ length: MAX_URLS }, (_, i) => `https://example.com/${i}`);
    const result = validateUrlsInput(urls.join("\n"));

    expect(result.urls).toEqual(urls);
    expect(result.errors).toEqual([]);
  });

  it("reports an error when there are more than MAX_URLS urls", () => {
    const urls = Array.from({ length: MAX_URLS + 1 }, (_, i) => `https://example.com/${i}`);
    const result = validateUrlsInput(urls.join("\n"));

    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toContain(String(MAX_URLS));
  });

  it("excludes blank lines without raising an error", () => {
    const result = validateUrlsInput(
      "https://example.com/a\n\n   \nhttps://example.com/b\n",
    );

    expect(result.urls).toEqual([
      "https://example.com/a",
      "https://example.com/b",
    ]);
    expect(result.errors).toEqual([]);
  });

  it("reports an error for a line that isn't a valid http(s) URL", () => {
    const result = validateUrlsInput("not-a-url");

    expect(result.urls).toEqual([]);
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toContain("not-a-url");
  });

  it("rejects non-http(s) schemes", () => {
    const result = validateUrlsInput("ftp://example.com/a\nfile:///etc/passwd");

    expect(result.urls).toEqual([]);
    expect(result.errors).toHaveLength(2);
  });

  it("silently deduplicates repeated urls instead of erroring", () => {
    const result = validateUrlsInput(
      "https://example.com/a\nhttps://example.com/a\nhttps://example.com/b",
    );

    expect(result.urls).toEqual([
      "https://example.com/a",
      "https://example.com/b",
    ]);
    expect(result.errors).toEqual([]);
  });

  it("mixes valid, invalid, blank, and duplicate lines correctly", () => {
    const result = validateUrlsInput(
      [
        "https://example.com/a",
        "",
        "not-a-url",
        "https://example.com/a",
        "https://example.com/b",
        "   ",
      ].join("\n"),
    );

    expect(result.urls).toEqual([
      "https://example.com/a",
      "https://example.com/b",
    ]);
    expect(result.errors).toEqual(["「not-a-url」はhttp(s)://で始まる正しいURLではありません"]);
  });
});
