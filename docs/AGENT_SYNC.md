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
Milestone: 里程碑 A/B/C/D 均已通过；本节复核的是里程碑之外、用户直接与执行会话交互的
  "候选证据口径收紧 + R2 模型研究"这一轮工作。当前处于等待用户对许可决策表态的状态。
Base commit: f16ec8e
Writer: 下一个读取本文件的执行 agent（Claude 或 Codex），需先等下方许可决策有答复

Review note（复核 262a2b4 / c0bf6d0 / f144b1d / c0b5df6 / 97895f6 / 38dde88 / d10b893 /
f16ec8e，均通过；另有一项已核实的紧急事项见下）:

  1. `262a2b4`（candidate_mask_admission 收紧为只认 VERIFIED）：独立重跑
     `tests/test_milestone_d_candidate_mask_admission.py` → 36/36 通过（含新增的 5 项
     HISTORICAL 边界回归）。核对改动只有一行判定条件，两张真实候选卡片字段值未被触碰。通过。

  2. `f144b1d`/`c0b5df6`（R2 纯文字资料复核：Prima v2、EfficientNetB1、BRISC）：只改了
     `docs/annotation_tumor_plan.md`，全部是论文/仓库公开页面的重新核对，没有下载、没装依赖、
     没跑代码，符合用户"本轮只做文字研究"的限定。通过。

  3. **紧急事项（已由用户确认，非违规）**：复核过程中发现 `97895f6`/`38dde88` 提交记录的
     "只读 config.json、未下载权重"，在提交后 1-2 分钟内被同一工作树里的执行会话（Codex）
     实际下载了两个 NeuroVFM 仓库合计约 290MB 的 `pytorch_model.bin`，且当时没有对应的 git
     提交或反馈包同步这一事实——审查会话在 Git 记录与磁盘现实出现分歧的窗口期发现此事，
     立即中断常规审查向用户确认；用户回复"是"，确认这次下载是本人当场直接指示执行会话做的
     （用户对执行会话说了"下载"）。执行会话随后自行在 `d10b893`/`f16ec8e` 里补上了完整记录，
     时间线是自洽的，不是执行会话擅自下载后被审查抓到才补记录。
     独立验证：现场对两个 blob 文件重新计算 SHA256，与 `d10b893` 记录的完全一致
     （encoder: `744cf058…8fc7`，286,576,042 字节；dx-mri: `e3db6eee…2492b`，3,789,726 字节）；
     `find . -iname pytorch_model.bin` 在本仓库工作树内为空，确认权重只存在于本机全局
     HuggingFace 缓存（`~/.cache/huggingface/hub/`），未被 git 跟踪、未进入产品目录。
     `SKIP_REAL_DATA=1 tests/test_gui.py` 仍 1487/1487，`git diff --check` 无残留。
     核对 `pyproject.toml:13` 确认本产品许可声明确实是 `Proprietary — All rights reserved`，
     与 NeuroVFM 官方 README 写明的权重许可 `CC-BY-NC-SA-4.0`（Non-Commercial Research Use）
     直接冲突——这是 `d10b893` 报告的关键发现，经独立核对属实，不是夸大或误读。
     这件事本身不构成对硬边界"不下载模型"的违反：该边界的精神是"不擅自下载"，用户当场
     明确说了"下载"就是对该次具体下载的显式授权，执行会话也确实止步于下载+哈希+读
     README，没有借这次授权顺势往前多做（没装依赖、没构造模型、没做任何推理）。
     记录在案供未来参考：以后这类"用户在执行会话里口头说一句话就授权了一个硬边界动作"的
     情况，如果能在动作发生前、或至少在同一条提交里就把授权来源写清楚（而不是让审查会话
     靠磁盘取证才发现），会更省事——不是要求走更重的流程，只是提醒记录要跟得上动作本身。

  未发现：病例身份混淆、把显示效果当数据正确性、放宽已生效的模型或医学功能边界、
  删检查绕过失败、伪造模型证据或运行结果、把这次下载/许可发现包装成产品已支持 NeuroVFM。

Decision requested（阻塞下一步；在收到答复前不建议安装新依赖、构造模型对象、执行任何推理，
或把这两个权重文件路径接入任何产品代码/`tumor_model_admission.py` 证据卡）：
  NeuroVFM 权重许可是 CC-BY-NC-SA-4.0（Non-Commercial Research Use），与本产品
  `Proprietary — All rights reserved` 的商业属性直接冲突。这份许可对 MUI 的使用场景是否可以
  接受（例如：本项目目前是否确实以商业/专有方式分发？是否已有或能取得官方的另行商用许可？）？
  这不是技术问题——不管后续 CPU 适配、推理验证结果多好，Non-Commercial 权重本身不能支撑
  商业产品的自动接入。回答决定的是继续投入 CPU 适配原型验证是否还有意义，而不是"能不能做"。

Next task: 无（等用户对上面的许可决策表态）。里程碑 A/B/C/D 的回归基线（累计 245+ 项里程碑
  专属测试 + 既有全套 1487 项测试）保持全绿，未受本轮任何改动影响，可继续作为强制门槛。
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
