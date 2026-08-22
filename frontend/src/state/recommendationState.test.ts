import { describe, expect, it } from "vitest";
import { recommendationErrorMessage } from "./recommendationState";

describe("recommendationErrorMessage", () => {
  it("maps Semantic Scholar failures to actionable copy", () => {
    expect(recommendationErrorMessage({
      response: { status: 429, data: { detail: { error: "semantic_scholar_error" } } },
    })).toBe("外部文献服务请求频率受限，请稍后再刷新。");
    expect(recommendationErrorMessage({
      response: { status: 504, data: { detail: { error: "semantic_scholar_error" } } },
    })).toBe("外部文献服务响应超时，请稍后重试。");
    expect(recommendationErrorMessage({
      response: { status: 502, data: { detail: { error: "semantic_scholar_error" } } },
    })).toBe("外部文献服务暂时不可用，请稍后重试。");
  });
});
