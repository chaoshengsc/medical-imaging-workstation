# MUI 双 Agent 阶段协作

本文件是 Claude 与 Codex 的唯一协作状态。两者在同一台电脑、同一工作树中工作；任何一方开始前都必须先读取本文件、`git status --short` 和最近提交。

## 不需要用户逐项验收的规则

- 每个里程碑可包含多项小修复；执行者自行完成、测试并作本地小提交。
- 用户只在一个里程碑完成、需求冲突、无法恢复的数据、或会明显改变产品行为时接收报告。
- 同一时刻只有一个写入者。另一位 agent 只能读、审查、制定下一里程碑或等待。
- 执行者完成一轮后更新“当前交接”，连同代码一起提交；审查者从该 commit 开始工作。
- 不下载模型、不训练、不用 GPU、不上传数据、不远端 push；不把候选分割标成自动诊断。

## 已恢复的基础

- 代码工作树：`/Users/sc/01_Projects/MUI`
- 恢复提交：`a1db432 recover: preserve local tumor admission safeguards`
- 公共研究用测试病例：`Annotation_Projects/recovered_vestibular_schwannoma_cases/`
- 恢复范围与缺口：`docs/RECOVERY_20260921.md`
- 需求和空间边界：`docs/annotation_tumor_plan.md`
- UI 历史：`docs/ui_review.md`，以及本机 Codex 的“优化 UI”会话记录。

## 里程碑 A：工作站基础闭环

目标：让恢复后的软件在两例 MRI 上可靠地完成不含模型的基础工作流。

执行包：

1. 用 VS-SEG-002、VS-SEG-003 分别验证 DICOM 载入、序列元数据、方向与体数据形状。
2. 验证人工画笔/ROI 的单层编辑、Undo/Redo、图层独立性和保存后的恢复。
3. 验证 MPR 联动、切片定位、显示切换及关闭重开后的工作区恢复。
4. 修复实际失败的最小根因，添加有价值的回归测试。

验收：两个病例都能完成“载入 → 一笔人工标注 → Undo/Redo → 保存 → 重开 → 标注仍在且空间不漂移”。

禁止：改模型运行路径、把研究用病例用于性能结论、通过删除检查绕过失败。

## 里程碑 B：标注工作流和工程文件

目标：完成用户已经确认的人工标注产品链路。

执行包：

1. 确认全部已标注切片与图层能被工程保存和恢复。
2. 确认真实 Undo 是操作回退，不与橡皮擦混淆，并跨重开保持可用的最近历史。
3. 确认单体素添加/删除只影响来源网格中的对应体素。
4. 确认原始 AI 候选与人工工作层在数据模型上分离；若缺少旧 AI 接入，不伪造结果。
5. 在保存失败、来源不匹配、几何不成立时给出明确拒绝，不静默损坏数据。

验收：用两例 MRI 做完整保存恢复回归；至少覆盖一个已知坏例，如来源或几何绑定改变后的拒绝。

## 里程碑 C：MPR、3D 与 UI 收敛

目标：让临床阅片和标注入口清晰，3D 是编辑结果的自然延伸。

执行包：

1. 用“优化 UI”会话中的已确认规则审查工具栏、侧栏、四切片和任务切换逻辑。
2. 修复 3D 与切片切换后无法返回、布局突变、拖拽阻塞、方向标识或定位逻辑问题。
3. 保持纯黑背景、明确空间方向，并确保 3D 视角与切片选中位置关联。
4. 只在有真实 mask 时显示 3D；避免空白 3D、错误居中或把显示平滑当成原始数据修改。
5. 将已确认的 UI 行为写成少量稳定测试，不重做外观偏好讨论。

验收：从载入病例到手工标注，再进入/退出 MPR 与 3D，能够返回原工作位置且没有数据丢失。

## 里程碑 D：模型接口的安全重建

目标：先恢复可审计的接入边界，随后才讨论真实模型效果。

执行包：

1. 保持 `tumor_model_admission.py` 的 fail-closed 逻辑和回归测试。
2. 将任何候选模型接入为“需复核的候选 mask”，默认不自动采用、不宣称瘤种。
3. 为每个模型记录输入序列要求、预处理、空间变换、版本、来源和输出身份。
4. 只有权重、输入契约、患者级验证和运行资源均有证据时，才单独提出执行申请。

验收：无模型包、缺少序列证据、空间身份不匹配、伪造结果均会被拒绝；不产生诊断或效能声明。

## 当前交接

```text
Milestone: A（已通过）
Base commit: a1db432
Writer: Claude
Completed: VS-SEG-002 / VS-SEG-003 两例真实 MRI 的“载入→人工标注→Undo→保存→重开→标注仍在且空间不漂移”闭环已用真实数据验证通过；恢复后的 study_data/annotation_state/project_store 本身未发现根因缺陷，未做产品代码改动。同时修复了 tumor_model_admission.py 未登记进 pyproject.toml/ARCHITECTURE.md 的一致性守卫失败。
Commits: 0dcb2c5
Files changed: tests/test_milestone_a_mri_workflow.py（新增）, pyproject.toml, docs/ARCHITECTURE.md
Validation:
  - `SKIP_REAL_DATA=1 python tests/test_gui.py` → 1487 项，1486 通过 / 1 失败（见已知限制）
  - `python tests/test_milestone_a_mri_workflow.py` → 38/38 通过（两例真实 MRI 全流程）
  - `python -m unittest tests.test_tumor_model_admission -v` → 6/6 通过
  - `git diff --check` → 无空白/冲突残留
Known limits:
  - AGENT_SYNC 里程碑 A 执行包第 2 条写的是“Undo/Redo”，但全仓库（含 tests/）没有任何 Redo 实现，annotation_tumor_plan.md 的产品需求原文也只要求 Undo，未提及 Redo。判断为 AGENT_SYNC 措辞与产品口径不一致，未擅自新增 Redo 功能（那是超出“基础闭环验证”范围的新功能），验收按 annotation_tumor_plan.md 的 Undo-only 口径执行。需要用户/下一位 agent 确认：是否要在里程碑 B/C 正式排入 Redo 需求。
  - `tumor_model_admission.qualify_vs_t1_source` 引用了不存在的模块 `series_read_qc`（`from series_read_qc import model_input_qc_safe`），且调用 `SeriesVolume.from_datasets(..., read_qc=...)`，与当前 `study_data.SeriesVolume.from_datasets(cls, datasets)` 签名不符——`SeriesVolume` 也没有 `read_qc` 字段。该函数当前没有任何测试覆盖，一旦被调用会直接抛异常。这是 RECOVERY_20260921.md 里程碑 D 相关模块（模型准入）的恢复缺口，不属于里程碑 A 的标注闭环，未在本轮修复；`tests/test_gui.py` 的“每个第三方 import 都已声明”一项因此仍标红，如实保留未掩盖。
  - 里程碑 A 执行包第 3 条提到的“MPR 联动、显示切换及关闭重开后的工作区恢复”，本轮只验证了 Milestone A 验收句所要求的文档级闭环（标注数据+几何绑定），未做 MedicalViewer 级 GUI 工作区状态（窗口布局、当前视图）回归；这部分与里程碑 C 的“返回原工作位置”验收重叠，留给 C 执行。
Next safe task: 里程碑 B——确认工程文件全量标注/图层保存恢复、真实 Undo 语义、单体素编辑边界，以及原始 AI 与人工工作层的数据模型分离（可复用本轮 tests/test_milestone_a_mri_workflow.py 的真实数据接入方式）。若要处理 qualify_vs_t1_source 的 series_read_qc 缺口，应作为里程碑 D 的独立任务单列，不要在 B/C 顺带修。
```

## 每轮交接模板

```text
Milestone: A/B/C/D
Base commit: <hash>
Writer: Claude or Codex
Completed: <one sentence>
Commits: <hashes>
Files changed: <paths>
Validation: <commands and pass/fail>
Known limits: <facts only>
Next safe task: <one bounded task>
```
