import { describe, expect, it } from "vitest";
import {
  parseCategoryItem,
  parseCategoryListResponse,
  parseTagItem,
  parseTagListResponse,
} from "./tags-categories-schema";

const TAG = { id: "tag-1", projectId: "project-1", name: "重要顧客" };
const CATEGORY = { id: "cat-1", projectId: "project-1", name: "キャンペーンA" };

describe("parseTagItem", () => {
  it("accepts a valid tag", () => {
    const result = parseTagItem(TAG);
    expect(result.success).toBe(true);
  });

  it("rejects a tag missing a required field", () => {
    const result = parseTagItem({ id: "tag-1", name: "x" });
    expect(result.success).toBe(false);
  });

  it("rejects a non-object", () => {
    expect(parseTagItem(null).success).toBe(false);
    expect(parseTagItem("not an object").success).toBe(false);
  });
});

describe("parseCategoryItem", () => {
  it("accepts a valid category", () => {
    expect(parseCategoryItem(CATEGORY).success).toBe(true);
  });

  it("rejects a malformed category", () => {
    expect(parseCategoryItem({ id: "cat-1" }).success).toBe(false);
  });
});

describe("parseTagListResponse", () => {
  it("accepts an empty tag list", () => {
    const result = parseTagListResponse({ tags: [] });
    expect(result).toEqual({ success: true, data: { tags: [] } });
  });

  it("accepts a populated tag list", () => {
    const result = parseTagListResponse({ tags: [TAG] });
    expect(result).toEqual({ success: true, data: { tags: [TAG] } });
  });

  it("rejects a response missing the tags array", () => {
    expect(parseTagListResponse({}).success).toBe(false);
  });
});

describe("parseCategoryListResponse", () => {
  it("accepts an empty category list", () => {
    const result = parseCategoryListResponse({ categories: [] });
    expect(result).toEqual({ success: true, data: { categories: [] } });
  });

  it("accepts a populated category list", () => {
    const result = parseCategoryListResponse({ categories: [CATEGORY] });
    expect(result).toEqual({ success: true, data: { categories: [CATEGORY] } });
  });

  it("rejects a response missing the categories array", () => {
    expect(parseCategoryListResponse({}).success).toBe(false);
  });
});
