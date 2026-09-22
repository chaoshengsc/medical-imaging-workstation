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
Milestone: D（立即执行；不等待新的用户任务，item 4 的决策问题已单独列出，不阻塞 D）
Base commit: c236aab
Writer: 下一个读取本文件的执行 agent（Claude 或 Codex）

Review note（复核里程碑 C 两个反馈包 ef73100 / f49c369，均通过）:
  - 复核方式：不看反馈包记录，直接重跑五条验收命令，现场产出与两份反馈包记录逐项一致：
    `.../python tests/test_milestone_a_mri_workflow.py` → 38/38（防回归）。
    `.../python tests/test_milestone_b_annotation_workflow.py` → 76/76（防回归）。
    `.../python tests/test_milestone_c_workspace_continuity.py` → 44/44（VS-SEG-002/003 各 22 项：
    任务切换相机连续性、四窗/单窗切换相机保持、标注+切换全流程保存重开无丢失、3D 可用性门槛）。
    `SKIP_REAL_DATA=1 .../python tests/test_gui.py` → 1486/1487，失败项仍是且只是已知的
    series_read_qc 未声明，与里程碑 A/B 时完全一致，无新增回归。
    `.../python -m unittest tests.test_tumor_model_admission -v` → 6/6。
  - `git diff --stat ff400ad..c236aab -- . ':!docs/AGENT_SYNC.md'` 确认整个里程碑 C 唯一改动的
    产品代码是 annotation_lab.py（21 行），改动内容是 tests/test_milestone_c_workspace_continuity.py。
  - 核对 annotation_lab.py 的 `_mesh3d_ready` 改动：旧逻辑下 3D 按钮使能只看 `self._organ_stats`
    非空（不检查方向/间距/z 轴几何有效性，那些校验只在 `show_mesh3d` 内部生效，等于旧代码存在“按钮
    可点但点了没反应”的状态）；`_compute_organ_stats` 又无条件要求 `hu_calibrated`，而
    `study_data.py:145` 对所有非 CT 模态强制把 `hu_calibrated` 置假——这是 annotation_tumor_plan.md
    明确要求的“HU 证明仅在 CT 入口有效”设计。净效果是 MR 病灶标注下 3D 预览永远不可达，与 mask
    是否有真实内容完全无关。新的 `_mesh3d_ready`（方向/间距/z 轴几何有效 + mask 内确有体素）对
    按钮使能是老条件的超集（更严且覆盖了旧代码的空当），对 CT 路径不构成回退。
  - 现场用一个独立探针复现了修复前的问题描述、又用当前代码复现了修复后的行为：在 VS-SEG-002 上
    画一笔病灶、确认 `btn_mesh3d.isEnabled()` 为真、`show_mesh3d` 产出非空网格且体积统计为正，
    撤销回空蒙版后按钮重新禁用——与测试断言逐项吻合，不是只看测试通过数字。
  - 里程碑 C 停止条件核查：item 4（3D 视角随当前切片/病灶位置联动）被工作会话正确识别为
    “『优化 UI』会话未确认过的产品可见行为”并主动停手，未擅自实现，处理方式恰当——这正是
    上一轮交接写明的停止条件之一，被正确触发而不是被绕过。
  - 未发现：病例身份混淆、把显示效果当数据正确性、放宽模型或医学功能边界、删检查绕过失败、
    为了让测试通过而弱化产品校验。
  - 结论：里程碑 C 验收句（载入→标注→进入/退出 MPR 与 3D→返回原工作位置且无数据丢失）已被
    `_case_tab_switch_continuity` / `_case_layout_switch_continuity` / `_case_reopen_no_data_loss`
    在真实 MedicalViewer 实例上逐字段验证，字面达成，予以通过。item 4 是里程碑 C 执行包的
    锦上添花项，不在验收句字面范围内，不阻塞通过判定，见下方单列的决策请求。

Decision requested（不阻塞下方 Next task，用户方便时回复即可）:
  里程碑 C 执行包第 3 条“3D 视角与切片选中位置关联”仍未实现：`show_mesh3d`/`_show_mesh_dialog`
  的初始视角是固定的 `azimuth=30.0, elevation=20.0`，与 `current_3d_pos`（当前切片/病灶选中位置）
  没有任何连接。这是一个新交互行为，之前任何一轮“优化 UI”会话都没有确认过具体该怎么定义
  （例如：打开 3D 时按当前切片位置自动选一个能看清该层病灶的默认方位角？还是只需要保证 3D
  弹窗打开时相机中心对准当前病灶质心，方位角仍固定？）。是否要做、以及做成什么行为，需要用户
  给一句明确定义；在收到之前不会去改 mesh3d.py 或 annotation_lab.py 的视角逻辑。

Next task（里程碑 D，一项连续执行任务，可直接认领，不等待用户确认，不等待上面的决策）:
  目标：按 AGENT_SYNC 里程碑 D 执行包第 1 条，修复 `tumor_model_admission.qualify_vs_t1_source`
  自里程碑 A 起就记录在案、至今未处理的一个具体缺陷，恢复该函数本身的可运行性和 fail-closed 保证，
  不是新增模型接入、不是讨论真实模型效果（那是执行包第 2-4 条，需要真实权重/患者级验证证据，
  本轮明确不做）。
  已核实的具体缺陷（供直接定位，不必重新排查）：
    - tumor_model_admission.py:365 `from series_read_qc import model_input_qc_safe`——
      `git log --all --oneline -- 'series_read_qc*'` 返回空，`git log --all -p -- \
      tumor_model_admission.py` 显示这一行是 a1db432 恢复提交整段新增的，此仓库历史上从未存在过
      `series_read_qc` 模块或任何提交删除过它——这不是“恢复丢失了一个文件”，而是恢复进来的代码
      引用了一个从未被实现过的模块。函数一旦被调用会在这一行直接 ModuleNotFoundError，且这行在
      try/except 之外，不会被 373 行的 `except (AttributeError, TypeError, ValueError)` 兜住。
    - tumor_model_admission.py:373 `SeriesVolume.from_datasets(series.datasets,
      read_qc=series.read_qc)`——当前 `study_data.py:130 SeriesVolume.from_datasets(cls, datasets)`
      不接受 `read_qc` 关键字参数；`study_data.py:100-113` 的 `SeriesVolume` dataclass 字段里
      也没有 `read_qc`。`series.read_qc`（对真实 `SeriesVolume` 实例取该属性）本身就会先于函数
      调用抛 `AttributeError`。
  允许修改文件：
    - tumor_model_admission.py（仅限 `qualify_vs_t1_source` 函数体本身，不改其他准入函数、
      不改 `EvidenceState`/`SequenceEvidenceState` 等既有词汇表、不放宽任何现有拒绝条件）
    - tests/test_milestone_d_*.py（新增，命名类比 test_milestone_a/b/c，用 VS-SEG-002/003
      真实数据构造 `SeriesVolume` 后调用 `qualify_vs_t1_source`）
    - docs/AGENT_SYNC.md（收尾更新“当前交接”，含 Feedback for review 反馈包）
    - docs/ARCHITECTURE.md / pyproject.toml（仅在发现新的登记缺口时同步）
  禁止修改：`tumor_model_admission.py` 中除 `qualify_vs_t1_source` 外的其他函数；`study_data.py`
  的 `SeriesVolume` 字段或 `from_datasets` 签名（缺口在调用方，不在被调用的数据层，不要反过来
  给 `SeriesVolume` 加字段迁就一个从未实现过的引用）；不得虚构或安装 `series_read_qc` 模块；
  不得让任何一支模型的运行路径变得可达；不得下载模型、训练、用 GPU、上传数据、远端 push。
  处理方式的边界（这是修复一个坏引用，不是设计新 QC 语义）：
    - `qualify_vs_t1_source` 原本想验证的是“重建的 SeriesVolume 与传入的是否一致”外加一项
      “读取质量”检查（`model_input_qc_safe`）。既然 `read_qc` 概念在当前数据层完全不存在、
      也找不到任何历史版本可恢复，正确做法是让这一步的校验只依赖当前 `SeriesVolume` 实际提供的
      字段（`volume`/`source_binding`/`affine`/`geometry_binding`，函数后半段已经在用这些做
      逐项比较），去掉对不存在字段的引用，而不是编造一个新的 `read_qc` 实现或 `model_input_qc_safe`
      函数去“让它能跑”。
    - 如果去掉 `read_qc` 相关校验后，函数在任何真实或构造的坏例上会从“拒绝”变成“通过”
      （即 read_qc 曾经把某类真实缺陷挡在外面，去掉之后不再挡得住），必须停手，把这个具体的
      安全性倒退写入 Known limits / Decision requested，不能为了让函数能跑而默默降低准入门槛。
    - 至少构造一个真实 VS-SEG-002/003 数据驱动的正例（`qualify_vs_t1_source` 对真实合规序列
      返回 qualified=True）和至少一个反例（如篡改 `source_binding` 摘要、破坏 `geometry_binding`，
      或传入非 `SeriesVolume` 对象），验证 fail-closed 行为不因本次改动而放宽。
  验收命令（新增 D 专属回归 + 复跑 A/B/C 防回归）：
    - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_a_mri_workflow.py`（须仍 38/38）
    - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_b_annotation_workflow.py`（须仍 76/76）
    - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_c_workspace_continuity.py`（须仍 44/44）
    - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_d_*.py`（新测试须全绿，列出比例）
    - `SKIP_REAL_DATA=1 /opt/miniconda3/envs/dicom_gui/bin/python tests/test_gui.py`（这一步预期
      从 1486/1487 变为 1487/1487——series_read_qc 未声明这一项失败应随缺口修复而消失；如果修复
      方式仍保留对不存在模块的引用，此断言不会转绿，说明修复不完整）
    - `/opt/miniconda3/envs/dicom_gui/bin/python -m unittest tests.test_tumor_model_admission -v`（须仍 6/6）
  停止条件（遇到以下情况立即停止写产品代码，只记录交接，交回复核）：
    - 需要真实模型权重、患者级验证证据或运行资源才能继续（那是执行包第 2-4 条，本轮不做）；
    - 去掉 read_qc 校验会让某个已知或可构造的坏例从拒绝变成通过（安全性倒退，不能默默接受）；
    - 需要修改 `qualify_contrast_enhanced_t1` 等其他准入函数或既有词汇表才能让 `qualify_vs_t1_source`
      工作（说明问题比预期更广，应先汇报再决定范围）。
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

## 当前交接（里程碑 D 反馈包：执行包第 1 条）

```text
Feedback for review
Commit: 6ca0465
Scope completed: 修复 tumor_model_admission.qualify_vs_t1_source 自 a1db432 恢复提交起就存在的
  坏引用——`from series_read_qc import model_input_qc_safe`（该模块在本仓库全部历史中从未存在过）
  和 `SeriesVolume.from_datasets(..., read_qc=series.read_qc)`（当前 SeriesVolume 没有 read_qc
  字段）。这两处都在 try/except 之外，此前该函数每次被调用都会直接 ModuleNotFoundError，从未
  返回过任何 VSQualificationDecision。去掉这两处引用后，函数走剩下本来就有的真实校验（模态匹配、
  几何/来源绑定存在性、与原始 SeriesVolume 逐字段重建比对）。因为修复前函数从未产出过一次真实的
  “拒绝”结果，这次改动不构成 fail-closed 倒退——是用真正的判定取代了崩溃，不是放宽了已生效的判定。
  未改 tumor_model_admission.py 中除这一个函数外的任何内容，未改 study_data.py 的字段或签名，
  未虚构或安装 series_read_qc。
Files changed:
  - tumor_model_admission.py（仅 qualify_vs_t1_source 函数体，删 2 处坏引用，净减 4 行）
  - tests/test_milestone_d_vs_t1_source_qualification.py（新增）
Validation（逐条对应 AGENT_SYNC 要求的验收命令，均现场重跑非缓存结果）:
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_a_mri_workflow.py` → 38/38 通过（防回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_b_annotation_workflow.py` → 76/76 通过（防回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_c_workspace_continuity.py` → 44/44 通过（防回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_d_vs_t1_source_qualification.py` → 12/12 通过
    （VS-SEG-002、VS-SEG-003 各 6 项：正例 2 项 + 反例 4 项——非 SeriesVolume 输入、篡改
    source_binding 摘要、篡改患者空间 affine、少一帧数据集）
  - `SKIP_REAL_DATA=1 /opt/miniconda3/envs/dicom_gui/bin/python tests/test_gui.py` → **1487/1487 全绿**
    （按预期从 1486/1487 变化——series_read_qc 未声明是全树唯一一项失败，随缺口修复自然消失，
    不是靠放宽或删除该检查项本身）
  - `/opt/miniconda3/envs/dicom_gui/bin/python -m unittest tests.test_tumor_model_admission -v` → 6/6 通过
    （既有 6 项准入测试未受影响——它们测的是 `*_admission` 系列函数，与本次改的
    `qualify_vs_t1_source` 是不同函数）
  - `ruff check tumor_model_admission.py tests/test_milestone_d_vs_t1_source_qualification.py`
    → All checks passed；`git diff --check` → 无残留
Known limits / failures:
  - 里程碑 D 执行包第 2-4 条（候选模型接入为"需复核候选 mask"、记录每个模型的输入/预处理/空间变换/
    版本/来源、权重+契约+患者级验证+运行资源齐备才申请执行）均未开始——本轮按 AGENT_SYNC 明确划定
    的停止条件，只做第 1 条（修复现有 fail-closed 逻辑本身的可运行性），不做需要真实模型权重、
    患者级验证证据或运行资源的后续条目。
  - `qualify_vs_t1_request`（调用 `qualify_vs_t1_source` 的上层函数）及其他准入函数未做改动，
    也未新增针对它们的测试；本轮范围严格限定在 `qualify_vs_t1_source` 本身。
  - 未发现"去掉 read_qc 校验后某个已知坏例从拒绝变成通过"的情况——已用真实数据构造的 4 个反例
    （类型错误/来源摘要篡改/几何篡改/帧数篡改）在修复前后都会走到 `series_rebuild`/`series_volume`
    这两个既有 gate 并被拒绝，read_qc 从未是这些反例被拒绝的唯一原因（修复前它们根本到不了
    read_qc 那一行就已经 ModuleNotFoundError 崩溃了）。
Decision requested: 无（里程碑 C item 4 的决策请求仍单独挂在上面的历史交接记录里，不受本轮影响）。
Next safe task: 里程碑 D 执行包第 2 条——为候选模型（如 BiomedParse）设计"候选 mask"接入路径的数据
  模型（独立版本、默认不自动采用、不宣称瘤种），这一步需要先确认是否已有候选权重/代码可实际试跑，
  没有真实权重时应如实止步于数据模型设计和 fail-closed 测试，不写依赖不存在权重文件的"占位成功"。
```

## 当前交接（里程碑 D 反馈包：执行包第 2 条）

```text
Feedback for review
Commit: 4b0064d
Scope completed: 里程碑 D 执行包第 2 条——本仓库目前没有任何候选模型的真实权重/可运行代码
  （BIOMEDPARSE_CARD、VS_SEG_CARD 均为 automatic_execution=product_execution=False 的研究记录卡），
  因此本轮如实止步于"候选 mask 接入"的数据模型与 fail-closed 测试，不写依赖不存在权重文件的
  占位成功。新增两个纯函数（tumor_model_admission.py，纯新增，未改任何既有函数/dataclass/证据卡）：
  `candidate_mask_admission(card)`——比 product_execution_admission 更低但仍 fail-closed 的门槛
  （不要求 patient/negative/OOD 验证或 automatic_execution/product_execution，因为候选接入本身
  不会自动运行或自动采用；但仍要求 weights/code/license/input_contract/task_compatibility 齐备，
  且完全不读 type_scope）；`candidate_mask_provenance(card)`——未通过准入就拒绝生成，通过后返回
  固定形状的 provenance（origin=candidate-model、requires_review=True、auto_adopted=False、
  绑定 model_id/model_version），按构造就不含任何瘤种字段、不含置真的 adopted/active 标记。
Files changed:
  - tumor_model_admission.py（纯新增两个函数 + 两个模块级常量，未改动任何既有代码）
  - tests/test_milestone_d_candidate_mask_admission.py（新增）
Validation（逐条对应 AGENT_SYNC 要求的验收命令，均现场重跑非缓存结果）:
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_a_mri_workflow.py` → 38/38 通过（防回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_b_annotation_workflow.py` → 76/76 通过（防回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_c_workspace_continuity.py` → 44/44 通过（防回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_d_vs_t1_source_qualification.py` → 12/12 通过（防回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_d_candidate_mask_admission.py` → 31/31 通过
    （两个真实候选仍被拒绝 4 项 + 门槛本身的 fail-closed 负例 5 项 + 不宣称瘤种 5 项 +
    VS-SEG-002/VS-SEG-003 各 8 项真实数据接入契约）
  - `SKIP_REAL_DATA=1 /opt/miniconda3/envs/dicom_gui/bin/python tests/test_gui.py` → 1487/1487 全绿（保持）
  - `/opt/miniconda3/envs/dicom_gui/bin/python -m unittest tests.test_tumor_model_admission -v` → 6/6 通过
    （既有 6 项未受影响，本轮是纯新增）
  - `ruff check tumor_model_admission.py tests/test_milestone_d_candidate_mask_admission.py`
    → All checks passed；`git diff --check` → 无残留
Known limits / failures:
  - 只交付了准入闸门本身（纯函数，无 I/O、无 Qt），没有在 main.py/annotation_lab.py/ai_engine.py
    里接一个真实的"运行模型→调用 candidate_mask_admission→写入 document"的按钮或后台任务——
    没有真实模型可以触发这条路径，本轮判断为没有真实调用方时提前写这段接入代码属于"为假设的未来
    预先设计"，按 CLAUDE.md 的既有原则未做；真实数据集成测试改用直接调用
    `StudyDocument.add_ai_result`/`adopt_ai_result` 的方式验证接入契约本身成立，不是通过真实 UI
    入口验证的。
  - `candidate_mask_admission` 对 weights/code 字段接受 EvidenceState.HISTORICAL（不只
    VERIFIED），这是本轮做出的一个具体口径选择：候选复核不等于产品自动执行，允许"历史上验证过、
    当前未重新核实"的证据进入人工复核队列。这个口径没有被用户单独确认过，如果审查认为过宽
    （例如应该要求 VERIFIED 才能进候选复核），请明确指出，改起来只是把
    `_CANDIDATE_EVIDENCE` 那行的 `(EvidenceState.VERIFIED, EvidenceState.HISTORICAL)` 收紧为
    `(EvidenceState.VERIFIED,)`，影响范围可控。
  - 里程碑 D 执行包第 3-4 条（为每个模型记录输入/预处理/空间变换/版本/来源的完整证据卡模板、
    权重+契约+患者级验证+运行资源齐备才申请执行）仍未开始。
Decision requested: 上面"Known limits"里的 HISTORICAL 口径是否需要收紧为只接受 VERIFIED？
  不阻塞下方 Next task。
Next safe task: 里程碑 D 执行包第 3 条——设计"每个候选模型的证据卡必须记录哪些字段才算完整"
  的模板/校验（输入序列要求、预处理步骤、空间变换约定、版本、来源、输出身份），可以先对
  BIOMEDPARSE_CARD/VS_SEG_CARD 现有字段做一次逐项审计，指出哪些字段当前是 NOT_ESTABLISHED/
  PENDING/UNKNOWN 且缺一句"如何补齐"的说明，而不是新增运行代码。
```
