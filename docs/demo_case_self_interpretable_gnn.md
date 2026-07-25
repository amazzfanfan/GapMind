# Demo Case：Self-Interpretable GNN 在分布偏移下的可信度

> Case ID：`demo-sig-ood-v1`
> Corpus Version：`sig-ood-smoke-v1`
> 状态：开发与回归基线
> 规则：本文件不预先声明研究空白成立；最终结论必须由原文证据和外部检索共同决定。

## 1. Demo 目标

证明 GapMind 不会把“解释性 + 分布偏移”简单拼接成研究空白，而会：

1. 从 Workspace 论文中找到解释方法的适用范围、局限和评估条件；
2. 主动检索部分覆盖该问题的外部工作；
3. 展示支持证据、相似工作、反证和未知项；
4. 将收窄后的 Opportunity 交给用户确认；
5. 从确认版本生成可证伪的验证计划。

## 2. 受控 Smoke Corpus

以下 12 篇构成冻结的 `sig-ood-smoke-v1` 候选清单。导入前必须用 DOI、arXiv 或
Semantic Scholar ID 核对题名和版本；评测 manifest 使用外部 ID，不使用标题字符串作为主键。

### A. Post-hoc explanation

1. GNNExplainer: Generating Explanations for Graph Neural Networks
2. PGExplainer: Parameterized Explainer for Graph Neural Network
3. PGM-Explainer: Probabilistic Graphical Model Explanations for Graph Neural Networks
4. SubgraphX: Towards Explaining Graph Neural Networks via Monte Carlo Tree Search

### B. Self-interpretable / intrinsic rationale

5. ProtGNN: Towards Self-Explaining Graph Neural Networks
6. Prototype-based Graph Information Bottleneck（PGIB；导入时核对正式题名）
7. Interpretable and Generalizable Graph Learning via Stochastic Attention Mechanism（GSAT）
8. Discovering Invariant Rationales for Graph Neural Networks（DIR）

### C. Evaluation and critical evidence

9. GraphFramEx: Towards Systematic Evaluation of Explainability Methods for Graph Neural Networks
10. Zorro: Valid, Sparse, and Stable Explanations in Graph Neural Networks

### D. Distribution shift context

11. GOOD: A Graph Out-of-Distribution Benchmark
12. OOD-GNN: Out-of-Distribution Generalized Graph Neural Network

现有本地验证过的 GIP、PGIB、ProtGNN 中，只有与上述清单核对过外部 ID 的论文才计入
corpus。`GIP` 的缩写可能对应多个工作，在题名和 ID 未核对前不得作为 benchmark 标签。

## 3. Corpus Manifest 必填字段

每篇论文进入评测前记录：

```json
{
  "paper_id": "local UUID",
  "semantic_scholar_paper_id": "external stable ID",
  "title": "verified title",
  "version": "publisher/arXiv version",
  "role": ["intrinsic", "evaluation", "overlap"],
  "pdf_source": "URL or manual",
  "artifact_id": "parsed_markdown UUID",
  "artifact_sha256": "hash",
  "parse_version": "v1",
  "extraction_prompt_version": "extract_v1",
  "annotation_status": "unreviewed|silver|gold"
}
```

## 4. 主 Opportunity Case

### Research topic

Self-interpretable GNN 的内在解释在真实图分布偏移下是否仍然忠实、稳定并具有预测效用？

### 初始线索（不是结论）

- 自解释方法通常把可解释子图、原型或随机注意力作为预测依据。
- 许多解释评估集中在单一数据分布或合成 motif。
- OOD 工作关注泛化，但未必同时评价解释的忠实度和稳定性。
- DIR、GSAT 或其他 invariant rationale 工作可能已经部分覆盖该组合，因此必须作为
  overlap/counter-evidence 检查，不能声称“从未有人研究”。

### Discover 必须回答

1. 哪些自解释方法明确在 OOD / distribution shift 上评估过？
2. 哪些工作只验证预测泛化，没有验证解释忠实度？
3. 哪些 explanation benchmark 的指标可用于 shift 前后比较？
4. DIR、GSAT 及外部检索结果与候选问题重叠到什么程度？
5. 真正尚未解决的是新方法、评测协议、特定 shift 类型，还是解释稳定性定义？

### 合格 Opportunity 的收窄方式

系统应把宽泛的“研究 OOD 下的可解释 GNN”收窄为可核验的问题，例如：

> 在 covariate、concept 或 size shift 中，比较 intrinsic rationale 与 post-hoc explanation
> 的 faithfulness、stability 和 predictive utility 是否同步退化，并识别哪类训练目标能降低
> 解释退化。

该表述仍只是候选。若外部工作已覆盖同样 setting、metric 和 intervention，系统必须继续
收窄或拒绝该 Opportunity。

### 必须出现的证据槽位

- 至少 2 篇自解释方法论文的范围或实验设置原文；
- 至少 1 篇解释评估论文的指标或批判性原文；
- 至少 1 篇 OOD 工作的 shift 定义或 benchmark 原文；
- 至少 1 篇 overlap/counter-evidence；
- 所有关键判断均指向可复现的 artifact + char offset。

### 弱/无效输出

- “Future work 提到 OOD，因此这是研究空白。”
- “没有在当前 12 篇论文中找到，所以领域无人研究。”
- 只罗列解释论文和 OOD 论文，没有指出 setting、metric 或方法差异。
- 没有相似工作、反证或证据定位。
- 验证计划只有“做实验并比较准确率”。

## 5. 参考验证计划结构

- Research Question：不同 graph shift 下，intrinsic rationale 的 faithfulness 与预测性能是否
  发生可分离的退化？
- Hypothesis：concept shift 对 rationale faithfulness 的破坏大于 covariate shift，且仅优化
  OOD accuracy 不能恢复解释稳定性。
- Datasets：从 GOOD 或其他已核验 benchmark 选择至少两类 shift。
- Baselines：至少一个 intrinsic 方法、一个 post-hoc 方法和一个 OOD 泛化方法。
- Metrics：预测指标 + faithfulness + stability；具体定义必须引用评估论文。
- Falsification：若多随机种子下各方法的解释指标无显著退化差异，或已知工作已覆盖相同设置，
  则候选假设不成立或缺乏新颖性。
- Constraints：比赛 Demo 只生成计划，不自动运行实验。

## 6. 轻量回归 Case

在主 Case 外保留以下四个回归问题；每个问题只需人工标注关键论文和一个反例：

1. Prototype explanations 是否在大图上存在计算或覆盖瓶颈？
2. Explanation faithfulness 与 stability 是否存在冲突？
3. Intrinsic 方法的解释是否一定优于 post-hoc 方法？
4. 合成 motif 上的解释质量是否能迁移到真实数据集？

## 7. 完成条件

该 Demo Case 只有在以下条件全部满足后才可用于正式演示：

- 12 篇论文的外部 ID 和 PDF 版本已核对；
- 至少 6 篇完成人工 evidence 抽查；
- 主 Case 至少有一项 gold overlap/counter-evidence；
- 关键检索答案有人工 relevance 标注；
- Opportunity 的确认、编辑、拒绝和延后路径均完成一次回归；
- 生成的 ResearchPlan 包含明确 falsification criteria。
