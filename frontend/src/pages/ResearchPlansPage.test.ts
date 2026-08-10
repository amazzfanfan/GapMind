import { describe, expect, it } from "vitest";
import { normalizeInlineMathVariables, normalizeMathMarkdown } from "./ResearchPlansPage";

describe("normalizeMathMarkdown", () => {
  it("把历史报告中的优化目标转换成可渲染的 LaTeX 块", () => {
    const markdown = [
      "### 优化目标",
      "",
      "L = MMD(P_source, P_target) + λ1 * LPIPS(x, x_cf) + λ2 * Causal_loss(x_cf)",
      "",
      "### 数学定义与候选公式",
    ].join("\n");

    const normalized = normalizeMathMarkdown(markdown);

    expect(normalized).toContain("$$\nL = \\operatorname{MMD}(P_{\\mathrm{source}}, P_{\\mathrm{target}})");
    expect(normalized).toContain("\\lambda_{1} \\cdot \\operatorname{LPIPS}(x, x_{\\mathrm{cf}})");
    expect(normalized).toContain("\\lambda_{2} \\cdot \\mathcal{L}_{\\mathrm{causal}}(x_{\\mathrm{cf}})\n$$");
  });

  it("把旧报告同一行的公式与中文解释拆开", () => {
    const normalized = normalizeMathMarkdown(
      "## 优化目标\n\nL(z') = MMD(f(z'), f(Y)) + λ * C(z', z, G)，其中z'为编码后的潜变量。",
    );

    expect(normalized).toContain("$$\nL(z') = \\operatorname{MMD}(f(z'), f(Y)) + \\lambda \\cdot C(z', z, G)\n$$");
    expect(normalized).toContain("\n\n其中z'为编码后的潜变量。");
  });

  it("把解释文字中的下标变量转换成行内数学公式", () => {
    const normalized = normalizeInlineMathVariables(
      "作用与解释：若存在边e_ij，则期望编辑对z_j的影响与z_i的变化一致。\n\n符号说明：z_i、z_j为潜变量分量。",
    );

    expect(normalized).toContain("边$e_{\\mathrm{ij}}$");
    expect(normalized).toContain("对$z_{j}$的影响与$z_{i}$的变化一致");
    expect(normalized).toContain("$z_{i}$、$z_{j}$为潜变量分量");
  });

  it("不会重复处理已有的行内公式或独立公式块", () => {
    const markdown = "$z_i$ 已经是公式。\n\n$$\nz_i + z_j\n$$";
    expect(normalizeInlineMathVariables(markdown)).toBe(markdown);
  });
});
