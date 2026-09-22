# MUI 双 Agent 阶段协作

本文件是 Claude 与 Codex 的唯一协作状态。两者在同一台电脑、同一工作树中工作；任何一方开始前都必须先读取本文件、`git status --short` 和最近提交。

## 不需要用户逐项验收的规则

- 每个里程碑可包含多项小修复；执行者自行完成、测试并作本地小提交。
- 用户只在一个里程碑完成、需求冲突、无法恢复的数据、或会明显改变产品行为时接收报告。
- 审查通过不是等待点：审查者必须把下一里程碑写入“当前交接”并立即由执行者认领。除非触发停止条件，不等待用户转述、确认或重新派发。
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
Milestone: B（立即执行；不等待新的用户任务）
Base commit: fb12d77
Writer: 下一个读取本文件的执行 agent（Claude 或 Codex）
Review note（复核里程碑 A，已通过）:
  - 复核方式：不看记录直接重跑三条验收命令，产出与 0dcb2c5/fb12d77 记录逐项一致。
    `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_a_mri_workflow.py` → 38/38 通过（VS-SEG-002/003 真实 DICOM 现场载入，非缓存结果）。
    `SKIP_REAL_DATA=1 .../python tests/test_gui.py` → 1486/1487，失败项与已知限制一致（series_read_qc）。
    `.../python -m unittest tests.test_tumor_model_admission -v` → 6/6。
  - 抽查 project_store.load_project_snapshot：确认“重开”是从磁盘 zip 重新解码整份 manifest + npz 层，
    重建全新 StudyDocument，不是复用内存对象或伪装成功；几何绑定按逐字段比较，不是形状比较。
  - 抽查“Undo/Redo 措辞差异”的已知限制：grep 全仓库确认没有任何 Redo 实现，
    annotation_tumor_plan.md 原文（第 25/49 行）也只写 Undo，判断为 AGENT_SYNC 措辞误差，
    此前 agent 未擅自新增功能，处理方式恰当。
  - 抽查 series_read_qc 缺口：git log 确认该 import 是 a1db432 恢复提交带入的既有缺口，
    不是本轮改出来的，未在里程碑 A 顺带“悄悄修好”掩盖问题，如实留给里程碑 D，处理方式恰当。
  - 未发现：病例身份混淆、把显示效果当数据正确性、放宽模型边界、或删检查绕过失败。
  - 结论：里程碑 A 验收句字面达成，且验证方法（真实数据、独立重开、逐字段比较）经得起复核，予以通过。
    docs/AGENT_SYNC.md 是本次唯一改动，未碰产品代码。

Next task（里程碑 B，一项连续执行任务）:
  目标：完成 annotation_tumor_plan.md 已确认的人工标注产品链路验收（里程碑 B 执行包 1-5 条），
  产出为新增/扩展的自动化回归测试 + 必要的最小根因修复，不是新功能。
  允许修改文件：
    - tests/test_milestone_b_*.py（新增，命名类比 tests/test_milestone_a_mri_workflow.py）
    - study_data.py / project_store.py / annotation_lab.py（仅限修复本轮验证中发现的真实根因缺陷；
      禁止为了让测试通过而放宽校验或删除既有断言）
    - docs/AGENT_SYNC.md（收尾更新“当前交接”）
    - docs/ARCHITECTURE.md / pyproject.toml（仅在发现新的登记缺口时同步，做法参照 0dcb2c5）
  禁止修改：tumor_model_admission.py 的模型准入逻辑与其测试（属里程碑 D，出问题单列任务，不顺带修）；
  不得触碰任何模型运行路径；不得引入 GPU/训练/下载权重。
  执行包对应的验证要点（用 VS-SEG-002、VS-SEG-003 真实数据，复用 test_milestone_a_mri_workflow.py 的接入方式）：
    1. 一次工程内产生多笔跨切片/跨图层标注，保存→重开，逐层逐体素比对，而非只比对单一体素。
    2. 连续多步编辑后 Undo 多步，确认每步都是精确回退（而非清空重画的近似效果），
       且跨“重开”后历史仍可继续 Undo（本轮已验证 1 步，B 需验证多步及 20 步上限，参照
       annotation_tumor_plan.md 第 28/104 行的“最近 20 个已完成操作”上限）。
    3. 单体素增删只影响来源网格中对应体素：构造边界/相邻体素的负例断言（本轮已覆盖单个相邻体素，
       B 需覆盖更多边界情形，如切片边缘、跨视图坐标转换后的体素）。
    4. 断言 working-manual 与原始 AI/候选图层在数据模型上物理隔离（不同数组、不同 key），
       若仓库当前没有真实旧 AI 结果可接入，如实报告“无旧 AI 数据可验证”，不得伪造结果验证通过。
    5. 至少构造一个已知坏例（保存失败磁盘写满/来源不匹配 series_uid 改写/geometry_binding 字段
       被篡改后拒绝载入），断言明确拒绝而不是静默损坏或吞异常。
  验收命令（新增 B 专属回归 + 复跑 A 防回归）：
    - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_a_mri_workflow.py`（须仍 38/38）
    - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_b_*.py`（新测试须全绿，列出比例）
    - `SKIP_REAL_DATA=1 /opt/miniconda3/envs/dicom_gui/bin/python tests/test_gui.py`（失败数不得超过
      当前已知的 1 项 series_read_qc；新增失败即视为回归，需先修复或如实记录为新的已知限制再交接）
    - `/opt/miniconda3/envs/dicom_gui/bin/python -m unittest tests.test_tumor_model_admission -v`（须仍 6/6）
  停止条件（遇到以下情况立即停止写产品代码，只记录交接，交回用户或下一位复核）：
    - 发现的根因缺陷修复会改变已确认的模型运行路径、医学功能边界或产品可见行为；
    - 需要新增 Redo 或其他 annotation_tumor_plan.md 未写明的功能才能让测试“通过”；
    - 无法用现有真实数据（VS-SEG-002/003）构造某条验收要点的真实反例，且伪造反例会掩盖问题；
    - 触及 tumor_model_admission.py 或 series_read_qc 缺口。
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
