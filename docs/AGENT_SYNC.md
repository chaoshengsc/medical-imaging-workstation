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
Milestone: C（立即执行；不等待新的用户任务）
Base commit: 614ccdd
Writer: 下一个读取本文件的执行 agent（Claude 或 Codex）

Review note（复核里程碑 B 反馈包 0d0a3eb，已通过）:
  - 复核方式：不看反馈包记录，直接重跑全部四条验收命令，现场产出与反馈包记录逐项一致：
    `.../python tests/test_milestone_a_mri_workflow.py` → 38/38（防回归，未受 B 改动影响）。
    `.../python tests/test_milestone_b_annotation_workflow.py` → 76/76（VS-SEG-002/003 各 38 项）。
    `SKIP_REAL_DATA=1 .../python tests/test_gui.py` → 1486/1487，失败项仍是且只是已知的
    series_read_qc 未声明，与里程碑 A 时完全一致，无新增回归。
    `.../python -m unittest tests.test_tumor_model_admission -v` → 6/6。
    `.../python -m ruff check tests/ pyproject.toml` → All checks passed。
  - `git show --stat 0d0a3eb` 确认唯一改动文件是新增的
    tests/test_milestone_b_annotation_workflow.py，未碰 study_data.py / project_store.py /
    annotation_lab.py 等产品代码，与反馈包“未发现需要修复的根因缺陷”的说法一致。
  - 通读测试源码逐条核对是否有“删检查/放宽校验/伪造数据”获得通过的迹象：
    * 20 步历史上限：核对 annotation_state.py:EditHistory（commands 列表 + `del
      self.commands[:-self.limit]`）和 EditCommand.apply 的显式 before/after 状态回放，
      证实“连续 25 笔后严格剩 20 步、回退 5/15/20 步精确复原”不是测试断言碰巧对上，
      而是真实的命令模式实现（非清空重画的近似效果）。
    * 单体素越界拒绝：核对 annotation_state.py 中 `Selection must match the source grid`
      等显式 ValueError 校验路径存在，负索引/越界索引确实会走真实拒绝分支。
    * 已知坏例注入：核对 `project_store._json_bytes` / `np.savez_compressed` /
      `os.replace` 三个 patch 目标在 project_store.py 中确实存在（61/463/481 行），
      不是 patch 一个不存在的属性导致 AttributeError 被误判为“测试通过”。
    * 几何篡改拒绝：`_rewrite_project` 重算了 manifest.sha256，证实 load_project_snapshot
      拒绝退化 affine 靠的是几何语义校验，不是仅靠 checksum 不匹配侥幸失败。
  - 抽查“无真实旧 AI 缓存”的已知限制：VS-SEG 恢复目录里确认没有历史 AI 推理产物，
    测试对此有醒目注释且只验证 add_ai_result 的隔离契约本身，未冒充这是真实历史模型结果，
    处理方式恰当，不构成“伪造 AI 数据”。
  - 未发现：病例身份混淆、把显示效果当数据正确性、放宽模型或医学功能边界、删检查绕过失败。
  - 结论：里程碑 B 验收句（两例 MRI 完整保存恢复回归 + 至少一个已知坏例）字面达成且实际交付
    超出下限（3 个已知坏例），验证方法经得起复核，予以通过。docs/AGENT_SYNC.md 是本次唯一改动。

Next task（里程碑 C，一项连续执行任务，可直接认领，不等待用户确认）:
  目标：按 AGENT_SYNC 里程碑 C 执行包 1-5 条，验证载入病例→人工标注→进入/退出 MPR 与 3D→
  能返回原工作位置且无数据丢失；产出为 Qt 级自动化回归测试（离屏，`QT_QPA_PLATFORM=offscreen`，
  参照 tests/test_gui.py 已有的 `QApplication` 离屏用法）+ 必要的最小根因修复，不是新功能、
  不是外观偏好重新讨论。
  已知的具体入口（供直接定位，避免现场重新摸索）：
    - main.py:447 `on_tab_changed`——临床阅片(0)/重建实验室(1) 切换，内部调用
      `_enter_recon_mode` / `_exit_recon_mode`，切换用 `setUpdatesEnabled(False)` 防闪烁。
    - main.py:659 `_anatomical_mpr_available`、main.py:665 `_sync_view_controls`——
      MPR 可用性与控件状态的联动判断。
    - main.py:752 `switch_layout`——四切片/其他布局切换时用 `_capture_view_camera` /
      `_restore_view_camera` 保存和恢复被隐藏视图的相机位置，是“返回原工作位置”的关键路径。
    - main.py 中 `btn_mesh3d`（约 272/945 行）与 mesh3d.py 的 `extract_surface` /
      `render_mesh`——3D 预览入口；mesh3d.py 用软件光栅化，不是外部 GPU/VTK 依赖。
  允许修改文件：
    - tests/test_milestone_c_*.py（新增，命名类比 test_milestone_a/b）
    - main.py / mesh3d.py / annotation_lab.py（仅限修复本轮验证中发现的真实根因缺陷：
      如返回不了原布局、方向标识错误、拖拽阻塞、空 mask 却显示 3D、把显示平滑误当数据修改；
      禁止为了让测试通过而放宽校验、删除既有断言或简化 UI 状态机语义）
    - docs/AGENT_SYNC.md（收尾更新“当前交接”，含 Feedback for review 反馈包）
    - docs/ARCHITECTURE.md / pyproject.toml（仅在发现新的登记缺口时同步）
  禁止修改：tumor_model_admission.py 与 series_read_qc 缺口（仍留给里程碑 D）；不得触碰模型运行路径；
  不得下载模型、训练、用 GPU、上传数据、远端 push。
  执行包对应的验证要点（用 VS-SEG-002、VS-SEG-003 真实数据，复用 `_load_case`/manifest 接入方式，
  但需要在 `m.MedicalViewer` 实例上跑，不能只测 Qt-free 数据层）：
    1. 工具栏/侧栏/四切片/任务切换（`on_tab_changed`、`switch_layout`）在真实病例上按“优化 UI”
       会话已确认规则逐条核对，记录核对结果而非重新讨论外观偏好。
    2. 载入→四切片浏览→切到重建实验室→切回临床阅片：断言切回后每个可见视图的相机位置/缩放
       （`_capture_view_camera` 的返回值）与切换前逐字段一致，而非仅断言“没有崩溃”。
    3. 保持纯黑背景与方向标识不变的前提下，验证 3D 预览只在 working 层确有非零 mask 时可用
       （`btn_mesh3d` 使能状态），空 mask 时保持禁用而非渲染空/错误居中的 3D。
    4. 3D 视角与当前切片/病灶选中位置的关联：改变切片定位后再打开 3D，断言 3D 视角参数
       随之更新，而不是停留在上一次打开时的默认视角。
    5. 进入/退出 MPR 与 3D 全流程不能丢失里程碑 A/B 已验证的标注数据：编辑后走一遍
       进入 3D→退出→保存→重开，复用 test_milestone_a 的逐体素/几何绑定比对方式断言无丢失。
  验收命令（新增 C 专属回归 + 复跑 A/B 防回归）：
    - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_a_mri_workflow.py`（须仍 38/38）
    - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_b_annotation_workflow.py`（须仍 76/76）
    - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_c_*.py`（新测试须全绿，列出比例）
    - `SKIP_REAL_DATA=1 /opt/miniconda3/envs/dicom_gui/bin/python tests/test_gui.py`（失败数不得超过
      当前已知的 1 项 series_read_qc；新增失败即视为回归）
    - `/opt/miniconda3/envs/dicom_gui/bin/python -m unittest tests.test_tumor_model_admission -v`（须仍 6/6）
  停止条件（遇到以下情况立即停止写产品代码，只记录交接，交回复核）：
    - 修复会改变已确认的模型运行路径、医学功能边界，或“优化 UI”会话未确认过的产品可见行为；
    - 需要真实 GPU/VTK 渲染或外部显示环境才能验证，离屏方式无法覆盖；
    - 无法用现有真实数据在离屏 Qt 环境下复现某条验收要点，且用截图人工判断代替自动化断言；
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

## 当前交接（里程碑 C 反馈包）

```text
Feedback for review
Commit: ef73100
Scope completed: 用 VS-SEG-002/VS-SEG-003 两例真实 MRI，通过离屏 Qt 的真实 MedicalViewer 实例
  （非 Qt-free 数据层）新增 tests/test_milestone_c_workspace_continuity.py，验证里程碑 C 执行包
  第 1/2/5 条：任务切换（临床阅片↔重建实验室）与四窗/单窗布局切换的相机连续性、以及标注+切换
  全流程+保存+新窗口重开后的数据/几何完整性。第 3/4 条（3D 预览的 mask 门槛、3D 视角随切片联动）
  未覆盖——用真实数据验证后确认是一个需要产品决策的已有缺口，见下方 Decision requested，
  未擅自修改 main.py/annotation_lab.py/mesh3d.py 的任何门禁逻辑。
Files changed:
  - tests/test_milestone_c_workspace_continuity.py（新增，唯一入库改动文件）
Validation（逐条对应 AGENT_SYNC 要求的验收命令，均现场重跑非缓存结果）:
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_a_mri_workflow.py` → 38/38 通过（防回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_b_annotation_workflow.py` → 76/76 通过（防回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_c_workspace_continuity.py` → 30/30 通过
    （VS-SEG-002、VS-SEG-003 各 15 项：载入/标注 3 项、任务切换相机+数据 5 项、布局切换相机 3 项、
    重开无丢失 4 项）
  - `SKIP_REAL_DATA=1 /opt/miniconda3/envs/dicom_gui/bin/python tests/test_gui.py` → 1486/1487 通过，
    失败数未超过已知的 1 项（series_read_qc 未声明），与里程碑 A/B 交接时完全一致，无新增回归
  - `/opt/miniconda3/envs/dicom_gui/bin/python -m unittest tests.test_tumor_model_admission -v` → 6/6 通过
  - `ruff check tests/test_milestone_c_workspace_continuity.py` → All checks passed；`git diff --check` → 无残留
Known limits / failures:
  - 执行包第 3/4 条未纳入自动化回归：用一次性探针脚本（未入库）在 VS-SEG-002 上现场验证——
    即使给 working-manual 图层画出一个真实的 400 体素病灶 mask，`btn_mesh3d.isEnabled()` 仍为 False，
    因为 `annotation_lab.py:_compute_organ_stats` 无条件要求 `hu_calibrated`，而
    `study_data.py:148` 对非 CT 模态强制把 `hu_calibrated` 置假（这是 annotation_tumor_plan.md
    明确要求的"HU 证明仅在 CT 入口有效"设计，不是本轮引入的缺陷）。结果是当前产品里 MR 病灶标注
    完全无法触发 3D 预览按钮，与其可用性判据完全无关于 mask 内容。这不违反验收句字面
    （没有出现"空白3D"，因为它压根不显示），但意味着"3D 视角与切片选中位置关联"这一条在真实 MR
    数据上根本无法验证——3D 预览此刻对 MR 标注工作流不可达。
  - 是否要让 3D 预览脱离 `hu_calibrated`/器官定量门槛、改为直接看 working-manual/病灶图层是否有
    非零 mask，是一个会改变产品可见行为的决定，且不在 docs/ui_review.md 任何一轮"优化 UI"已确认
    规则范围内（那些轮次全部基于 CT 工作流，早于 MR/VS-SEG 标注支持被恢复）。按里程碑 C 的停止
    条件（"『优化 UI』会话未确认过的产品可见行为"），本轮未擅自修改 mesh3d.py 或
    annotation_lab.py 的门禁逻辑，只如实记录现状。
  - series_read_qc 缺口仍未处理，继续留给里程碑 D，本轮未触碰 tumor_model_admission.py。
Decision requested: 是否要为 MR 病灶标注单独开一条 3D 预览可用性判据（不依赖 CT 专属的
  hu_calibrated/器官定量），直接以 working-manual 或病灶图层是否有非零体素为准？这决定了
  里程碑 C 第 3/4 条以及"进入/退出 3D"这部分验收要点该怎么继续；在收到方向前不会去改
  btn_mesh3d 的使能逻辑或 mesh3d.py。
Next safe task:
  - 若决定要做：把"3D 预览可用性"改为检查 working-manual/病灶图层非零体素（与 hu_calibrated
    解耦），限定只改 annotation_lab.py 的 `_update_organ_stats`/`btn_mesh3d` 使能路径，
    不改 mesh3d.py 内部渲染算法；再补 tests/test_milestone_c_*.py 里第 3/4 条的真实数据回归
    （3D 视角随 `current_3d_pos` 更新、无 mask 时保持禁用）。
  - 若决定暂不做：里程碑 C 按"MPR/任务切换连续性"部分验收通过、3D 相关两条明确标记为"MR 工作流
    暂不支持"推进里程碑 D（`tumor_model_admission.py` 的 fail-closed 逻辑与 series_read_qc 缺口）。
```

## 当前交接（里程碑 C 反馈包：第 3 条决策落地）

```text
Feedback for review
Commit: f49c369
Scope completed: 用户对上一轮 Decision requested 回复"做"，已实现：3D 预览可用性判据
  与 CT 专属的 hu_calibrated/器官 HU 定量解耦，改为只看几何是否有效 + 蒙版是否有真实体素
  （新增 annotation_lab.py:_mesh3d_ready，供 btn_mesh3d 使能与 show_mesh3d 自身门禁共用）；
  在 VS-SEG-002/003 真实 MR 上验证：空蒙版禁用→画出真实病灶体素后可用→show_mesh3d 产出非空
  网格（有正体积）→撤销回空后重新禁用，全程通过。mesh3d.py 的渲染/抽面算法未改动，
  CT 器官路径的 3D 可用性条件不变（对 CT 而言新判据是旧判据的超集，不改变现有行为）。
Files changed:
  - annotation_lab.py（_mesh3d_ready 新增；_update_organ_stats/show_mesh3d 改用它；
    _show_mesh_dialog 的标题兜底给 MANUAL_TRACK_LABEL 一个可读名，不再显示"label 255"）
  - tests/test_milestone_c_workspace_continuity.py（补执行包第 3 条的真实数据回归）
Validation（逐条对应 AGENT_SYNC 要求的验收命令，均现场重跑非缓存结果）:
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_a_mri_workflow.py` → 38/38 通过（防回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_b_annotation_workflow.py` → 76/76 通过（防回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_c_workspace_continuity.py` → 44/44 通过
    （比上一轮多 14 项：VS-SEG-002/003 各新增 7 项第 3 条 3D 可用性回归）
  - `SKIP_REAL_DATA=1 /opt/miniconda3/envs/dicom_gui/bin/python tests/test_gui.py` → 1486/1487 通过，
    失败数未超过已知的 1 项（series_read_qc 未声明），CT 器官/3D 既有测试均未受影响，无新增回归
  - `/opt/miniconda3/envs/dicom_gui/bin/python -m unittest tests.test_tumor_model_admission -v` → 6/6 通过
  - `ruff check annotation_lab.py tests/test_milestone_c_workspace_continuity.py` → All checks passed；
    `git diff --check` → 无残留
Known limits / failures:
  - 执行包第 4 条（3D 视角随当前切片/病灶选中位置联动）仍未实现：核对
    `show_mesh3d`/`_show_mesh_dialog` 后确认 `current_3d_pos` 与 3D 视角（`MeshView(azimuth=30.0,
    elevation=20.0)` 固定默认值）在代码里完全没有连接，这是一个需要单独设计的新功能（比如"3D 打开
    时自动摆到能看清当前切片对应位置的角度"具体该怎么定义），不在这次"做"的授权范围内
    （那次授权只针对第 3 条的可用性判据）。未擅自实现，留待下一次明确决策。
  - series_read_qc 缺口仍未处理，继续留给里程碑 D，本轮未触碰 tumor_model_admission.py。
Decision requested: 是否要继续做第 4 条（3D 视角随切片/病灶位置联动）？如果要做，需要先明确一句
  "视角联动"具体指什么行为（例如：打开 3D 时按 current_3d_pos 所在层的位置自动选一个能看到该层
  病灶的默认方位角，而不是固定 30°/20°），再评估要不要改 mesh3d.py 或只改
  _show_mesh_dialog 传入的初始角度。
Next safe task:
  - 若决定要做第 4 条：先在 annotation_lab.py 里加一个把 current_3d_pos 换算成初始
    azimuth/elevation 的纯函数（可放 mesh3d.py 或 annotation_lab.py，视是否需要几何库函数），
    `_show_mesh_dialog` 用它替换硬编码的 30.0/20.0；补真实数据回归：改变切片位置后重新打开 3D，
    断言初始视角随之变化。
  - 若决定第 4 条暂不做，或已经足够：里程碑 C 按当前范围（执行包 1/2/3/5）验收通过，推进里程碑 D
    ——`tumor_model_admission.py` 的 fail-closed 逻辑与 series_read_qc 缺口（该模块引用不存在的
    `series_read_qc.model_input_qc_safe`，且调用签名与当前 `study_data.SeriesVolume.from_datasets`
    不符，详见里程碑 A 交接时的记录）。
```
