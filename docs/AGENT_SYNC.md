# MUI 双 Agent 阶段协作

本文件是 Claude 与 Codex 的唯一协作状态。两者在同一台电脑、同一工作树中工作；任何一方开始前都必须先读取本文件、`git status --short` 和最近提交。

## 不需要用户逐项验收的规则

- 每个里程碑可包含多项小修复；执行者自行完成、测试并作本地小提交。
- 用户只在一个里程碑完成、需求冲突、无法恢复的数据、或会明显改变产品行为时接收报告。
- 审查通过不是等待点：审查者必须把下一里程碑写入“当前交接”并立即由执行者认领。除非触发停止条件，不等待用户转述、确认或重新派发。
- 同一时刻只有一个写入者。另一位 agent 只能读、审查、制定下一里程碑或等待。
- 执行者完成一轮后更新“当前交接”，连同代码一起提交；审查者从该 commit 开始工作。
- 不下载模型、不训练、不用 GPU、不上传数据、不远端 push；不把候选分割标成自动诊断。

## 自动反馈包与循环

工作会话每次完成一个写入阶段，必须在同一次提交中把下列反馈写入“当前交接”；缺少任一项，视为尚未交给审查：

```text
Feedback for review
Commit: <hash>
Scope completed: <one sentence>
Files changed: <paths>
Validation: <exact commands and pass/fail>
Known limits / failures: <facts only>
Decision requested: <none, or one concrete question>
Next safe task: <one bounded task>
```

循环固定为：**MUI 工作**完成实现和本地提交 → 写入上述反馈包 → **MUI 审查与规划**只基于该提交复核、记录结论并写出下一项任务 → **MUI 工作**认领下一项任务。审查结论不是等待点。

本文件和 Git 提交是两会话共享的可靠投递层：同一工作树中的反馈一经提交即可被审查会话读取。当前桌面环境没有向另一 Claude 会话自动输入消息或唤醒其执行的接口；因此不能把“文件已投递”表述成“审查会话已运行”。若未来有受支持的跨会话消息接口，再把最后一步替换成直接通知，不改变本记录格式。

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
2. 验证人工画笔/ROI 的单层编辑、Undo、图层独立性和保存后的恢复。
3. 验证 MPR 联动、切片定位、显示切换及关闭重开后的工作区恢复。
4. 修复实际失败的最小根因，添加有价值的回归测试。

验收：两个病例都能完成“载入 → 一笔人工标注 → Undo → 保存 → 重开 → 标注仍在且空间不漂移”。

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
Milestone: A/B/C/D 的工程验收已通过；NeuroVFM 权重契约、CPU state dict 读取及诊断头合成输入冒烟已通过。自动肿瘤分割与逐病灶分类未完成。
Base commit: 80be4cb（本轮研究开始点）
Writer: Codex；本轮仅研究脚本、定向测试和交接记录写入，未改产品运行路径。

Verified 2026-09-23:
  - A/B/C/D 基线见上一提交 80be4cb；本轮没有修改其产品代码，未把旧 PASS 当新性能证据。
  - 固定源码 MLNeurosurg/neurovfm@9240021，14 个文件的 Git blob 摘要通过；两个已缓存权重的 SHA256 与 d10b893 一致。
  - 静态审计：encoder 136 个张量、MRI 诊断头 16 个张量，键名/shape 与固定 config 精确一致；MRI 标签 74 个唯一项；9 项检查全通过。
  - PyTorch 2.5.1、4 CPU 线程、weights_only=True/mmap=True 成功读取两份 state dict，加载元数据逐张量一致；没有构造编码器。
  - 官方 ClassifyThenAggregate 在 CPU 替换 FusedDense 和 segment_csr 后，真实权重 strict=True 加载，用合成 patch 特征输出 [2,74]；两段注意力和误差 1.19e-7，分批与单独运行最大差 0；缺失键被拒绝。
  - 静态审计恶意 GLOBAL、未知 opcode、非张量顶层、错误摘要 4 个反例测试通过。具体命令与忽略目录下的 JSON 结果见 docs/annotation_tumor_plan.md 的 2026-09-23 节。

Limits:
  - 这不是从 MRI 到 74 标签的整模型推理；编码器 FlashAttention/BF16 路径、位置编码与预处理尚未跑通。没有真实病例效果或类型准确性结论。
  - 官方 StudyPreprocessor.load_study 对 DICOM 目录逐文件枚举，需先按 UID 建立正确的 3D 序列输入与几何记录。
  - NeuroVFM 只有检查级标签，不生成 mask，也不能自动把类型绑定至某个病灶；产品未接入其权重。
  - A/B 仅有 Undo 无 Redo；C 的主观 UI 验收仍不全；D 的准入拒绝门不是模型效能证明。
  - 当前非商用用途已确认；未来若分发权重或改变用途，仍核对许可、署名和分发条件。没有 push。

Feedback for review
Commit: 本提交（以 git log -1 的实际哈希为准）
Scope completed: 固定权重与源码静态契约核对、CPU 安全载入及官方检查级诊断头合成输入冒烟。
Files changed: experiments/neurovfm_static_audit.py, experiments/neurovfm_static_source_manifest.json, experiments/neurovfm_checkpoint_load_probe.py, experiments/neurovfm_cpu_head_probe.py, tests/test_neurovfm_static_audit.py, docs/annotation_tumor_plan.md, docs/AGENT_SYNC.md。
Validation: 见本节 Verified 和 docs/annotation_tumor_plan.md 的 2026-09-23 精确命令；本轮新产物均通过。
Known limits / failures: 完整编码器与真实 MRI 未跑；DICOM 目录输入契约有已定位缺口；诊断头不产生病灶 mask/类型绑定。
Decision requested: none。
Next safe task: 在忽略目录隔离实现固定 encoder 配置的 CPU 等价路径，先以小型合成输入对照注意力、残差归一化、MLP 和位置编码，再 strict 加载已下载权重；同时单独设计按 UID 选 3D DICOM 序列的输入适配及空间记录。达不到数值/空间核查时停止真实病例推理。4 线程、15 分钟、12 GiB 上限；不进入产品运行路径。自动分割仍需独立病灶模型。
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

## 反馈包模板（工作会话完成一轮后，在同一提交内附上）

```text
Feedback for review
Commit: <hash>
Scope completed: <one sentence>
Files changed: <paths>
Validation: <exact commands and pass/fail>
Known limits / failures: <facts only>
Decision requested: <none, or one concrete question>
Next safe task: <one bounded task>
```
