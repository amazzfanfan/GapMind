import { describe, expect, it } from "vitest";
import { normalizeConversationMath } from "./ChatMessages";

describe("normalizeConversationMath", () => {
  it("wraps bracket-wrapped display math in dollars", () => {
    const input = "[ \\min_{G_{sub}} \\left[ -I(G_{sub}, Y) + \\beta I(G_{sub}, G) \\right] ]";
    const out = normalizeConversationMath(input);
    // The outer `[ ... ]` becomes inline math; the inner \left[...\right] stays legal.
    expect(out).toContain("$\\min_{G_{sub}} \\left[");
    expect(out).toContain("\\right]$");
  });

  it("wraps parenthesis-wrapped simple math in dollars", () => {
    expect(normalizeConversationMath("( \\beta X )")).toBe("$\\beta X$");
    expect(normalizeConversationMath("(G_{sub})")).toContain("$G_{sub}$");
  });

  it("turns bare subscripts into inline math", () => {
    expect(normalizeConversationMath("G_{sub} 是子图")).toContain("$G_{\\mathrm{sub}}$");
    expect(normalizeConversationMath("G_sub 简化形式")).toContain("$G_{\\mathrm{sub}}$");
  });

  it("leaves plain brackets and single letters untouched", () => {
    expect(normalizeConversationMath("参考文献 [1] 和 (G)")).toBe("参考文献 [1] 和 (G)");
  });

  it("leaves valid $...$ math untouched", () => {
    const input = "目标函数 $\\min L$ 是最小值。";
    expect(normalizeConversationMath(input)).toBe(input);
  });
});
