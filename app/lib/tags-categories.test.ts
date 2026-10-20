import { describe, expect, it } from "vitest";
import {
  TAG_NAME_MAX_LENGTH,
  isValidTagOrCategoryName,
  normalizeTagOrCategoryName,
  resolveAttachTagOutcome,
  resolveCategoryListFetchOutcome,
  resolveCreateCategoryOutcome,
  resolveCreateTagOutcome,
  resolveDeleteCategoryOutcome,
  resolveDeleteTagOutcome,
  resolveDetachTagOutcome,
  resolveRenameCategoryOutcome,
  resolveRenameTagOutcome,
  resolveSetCategoryOutcome,
  resolveTagListFetchOutcome,
} from "./tags-categories";

describe("normalizeTagOrCategoryName", () => {
  it("trims leading/trailing whitespace", () => {
    expect(normalizeTagOrCategoryName("  重要顧客  ")).toBe("重要顧客");
  });
});

describe("isValidTagOrCategoryName", () => {
  it("rejects an empty or whitespace-only name", () => {
    expect(isValidTagOrCategoryName("")).toBe(false);
    expect(isValidTagOrCategoryName("   ")).toBe(false);
  });

  it("accepts a 1-character name after trimming", () => {
    expect(isValidTagOrCategoryName(" a ")).toBe(true);
  });

  it(`accepts exactly ${TAG_NAME_MAX_LENGTH} characters`, () => {
    expect(isValidTagOrCategoryName("a".repeat(TAG_NAME_MAX_LENGTH))).toBe(true);
  });

  it(`rejects ${TAG_NAME_MAX_LENGTH + 1} characters`, () => {
    expect(isValidTagOrCategoryName("a".repeat(TAG_NAME_MAX_LENGTH + 1))).toBe(false);
  });
});

const TAG = { id: "tag-1", projectId: "project-1", name: "重要顧客" };
const CATEGORY = { id: "cat-1", projectId: "project-1", name: "キャンペーンA" };

describe("resolveTagListFetchOutcome", () => {
  it("returns the parsed tag list on success", async () => {
    const response = new Response(JSON.stringify({ tags: [TAG] }), { status: 200 });
    const outcome = await resolveTagListFetchOutcome(response);
    expect(outcome).toEqual({ success: true, tags: [TAG] });
  });

  it("fails on a network-level error (null response)", async () => {
    const outcome = await resolveTagListFetchOutcome(null);
    expect(outcome.success).toBe(false);
  });

  it("fails on a non-2xx response", async () => {
    const outcome = await resolveTagListFetchOutcome(new Response("", { status: 500 }));
    expect(outcome.success).toBe(false);
  });
});

describe("resolveCategoryListFetchOutcome", () => {
  it("returns the parsed category list on success", async () => {
    const response = new Response(JSON.stringify({ categories: [CATEGORY] }), { status: 200 });
    const outcome = await resolveCategoryListFetchOutcome(response);
    expect(outcome).toEqual({ success: true, categories: [CATEGORY] });
  });
});

describe("resolveCreateTagOutcome", () => {
  it("returns the created tag on 201", async () => {
    const response = new Response(JSON.stringify(TAG), { status: 201 });
    const outcome = await resolveCreateTagOutcome(response);
    expect(outcome).toEqual({ success: true, data: TAG });
  });

  it("surfaces a 409 conflict as a failure with a message", async () => {
    const response = new Response(JSON.stringify({ error: "duplicate" }), { status: 409 });
    const outcome = await resolveCreateTagOutcome(response);
    expect(outcome.success).toBe(false);
    if (!outcome.success) {
      expect(outcome.message.length).toBeGreaterThan(0);
    }
  });

  it("surfaces a 401 as unauthorized", async () => {
    const outcome = await resolveCreateTagOutcome(new Response("", { status: 401 }));
    expect(outcome.success).toBe(false);
  });

  it("surfaces a 403 as forbidden", async () => {
    const outcome = await resolveCreateTagOutcome(new Response("", { status: 403 }));
    expect(outcome.success).toBe(false);
  });

  it("surfaces a 400 as invalid", async () => {
    const outcome = await resolveCreateTagOutcome(new Response("", { status: 400 }));
    expect(outcome.success).toBe(false);
  });
});

describe("resolveRenameTagOutcome", () => {
  it("returns the renamed tag on success", async () => {
    const response = new Response(JSON.stringify(TAG), { status: 200 });
    const outcome = await resolveRenameTagOutcome(response);
    expect(outcome).toEqual({ success: true, data: TAG });
  });

  it("surfaces a 404 as not found", async () => {
    const outcome = await resolveRenameTagOutcome(new Response("", { status: 404 }));
    expect(outcome.success).toBe(false);
  });
});

describe("resolveDeleteTagOutcome / resolveDeleteCategoryOutcome", () => {
  it("succeeds on 204 without parsing a body", async () => {
    const response = new Response(null, { status: 204 });
    const outcome = await resolveDeleteTagOutcome(response);
    expect(outcome).toEqual({ success: true });
  });

  it("succeeds on 204 for category delete too", async () => {
    const outcome = await resolveDeleteCategoryOutcome(new Response(null, { status: 204 }));
    expect(outcome).toEqual({ success: true });
  });

  it("fails on a 404", async () => {
    const outcome = await resolveDeleteTagOutcome(new Response("", { status: 404 }));
    expect(outcome.success).toBe(false);
  });
});

describe("resolveCreateCategoryOutcome / resolveRenameCategoryOutcome", () => {
  it("returns the created category on 201", async () => {
    const response = new Response(JSON.stringify(CATEGORY), { status: 201 });
    const outcome = await resolveCreateCategoryOutcome(response);
    expect(outcome).toEqual({ success: true, data: CATEGORY });
  });

  it("returns the renamed category on success", async () => {
    const response = new Response(JSON.stringify(CATEGORY), { status: 200 });
    const outcome = await resolveRenameCategoryOutcome(response);
    expect(outcome).toEqual({ success: true, data: CATEGORY });
  });

  it("surfaces a 409 conflict for category creation", async () => {
    const outcome = await resolveCreateCategoryOutcome(new Response("", { status: 409 }));
    expect(outcome.success).toBe(false);
  });
});

describe("resolveAttachTagOutcome / resolveDetachTagOutcome / resolveSetCategoryOutcome", () => {
  it("succeeds on 204 for attach", async () => {
    const outcome = await resolveAttachTagOutcome(new Response(null, { status: 204 }));
    expect(outcome).toEqual({ success: true });
  });

  it("succeeds on 204 for detach", async () => {
    const outcome = await resolveDetachTagOutcome(new Response(null, { status: 204 }));
    expect(outcome).toEqual({ success: true });
  });

  it("succeeds on 204 for set category (including clearing it)", async () => {
    const outcome = await resolveSetCategoryOutcome(new Response(null, { status: 204 }));
    expect(outcome).toEqual({ success: true });
  });

  it("surfaces a 409 as a status-conflict message for attach (queued/running run)", async () => {
    const outcome = await resolveAttachTagOutcome(new Response("", { status: 409 }));
    expect(outcome.success).toBe(false);
  });

  it("surfaces a 404 as not-found for detach (run or tag missing)", async () => {
    const outcome = await resolveDetachTagOutcome(new Response("", { status: 404 }));
    expect(outcome.success).toBe(false);
  });

  it("surfaces a 400 as the CategoryRequiresProjectError message for set category", async () => {
    const outcome = await resolveSetCategoryOutcome(new Response("", { status: 400 }));
    expect(outcome.success).toBe(false);
  });

  it("surfaces a 401 as unauthorized for every attach/detach/set endpoint", async () => {
    expect((await resolveAttachTagOutcome(new Response("", { status: 401 }))).success).toBe(
      false,
    );
    expect((await resolveDetachTagOutcome(new Response("", { status: 401 }))).success).toBe(
      false,
    );
    expect((await resolveSetCategoryOutcome(new Response("", { status: 401 }))).success).toBe(
      false,
    );
  });

  it("fails on a network-level error (null response)", async () => {
    expect((await resolveAttachTagOutcome(null)).success).toBe(false);
    expect((await resolveDetachTagOutcome(null)).success).toBe(false);
    expect((await resolveSetCategoryOutcome(null)).success).toBe(false);
  });
});
