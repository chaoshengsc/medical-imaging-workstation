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
Milestone: 全部四个（A/B/C/D）已完成第一轮；当前处于纯决策等待状态，不建议在收到用户答复前
  新增任何没有真实模型/真实调用方的候选接入代码。
Base commit: 2752056
Writer: 下一个读取本文件的执行 agent（Claude 或 Codex），需先等下方三个决策问题有答复

Review note（复核里程碑 D 四个反馈包 6ca0465 / 4b0064d / f85086f / feef2be，均通过）:
  - 复核方式：不看反馈包记录，直接重跑全部十一条验收命令，现场产出与四份反馈包记录逐项一致：
    `.../python tests/test_milestone_a_mri_workflow.py` → 38/38；
    `.../python tests/test_milestone_b_annotation_workflow.py` → 76/76；
    `.../python tests/test_milestone_c_workspace_continuity.py` → 44/44；
    `.../python tests/test_milestone_d_vs_t1_source_qualification.py` → 12/12；
    `.../python tests/test_milestone_d_candidate_mask_admission.py` → 31/31；
    `.../python tests/test_milestone_d_evidence_card_completeness.py` → 14/14；
    `.../python tests/test_milestone_d_execution_request_admission.py` → 20/20；
    `SKIP_REAL_DATA=1 .../python tests/test_gui.py` → **1487/1487 全绿**（series_read_qc 缺口
    确认随第 1 条修复消失，不是靠放宽或删除该检查项本身）；
    `.../python -m unittest tests.test_tumor_model_admission -v` → 6/6；
    `.../python -m ruff check .`（全仓库）→ All checks passed；`git diff --check` → 无残留。
  - `git diff --stat 00757f8..2752056 -- . ':!docs/AGENT_SYNC.md'` 确认整个里程碑 D 只改了
    tumor_model_admission.py（119 行，纯新增四个函数 + 删掉第 1 条的两处坏引用）和四个新测试
    文件，未碰 study_data.py / annotation_lab.py / main.py / mesh3d.py。
  - `git diff 00757f8..2752056 -- tumor_model_admission.py | grep '^-' ` 逐行核对：全部四轮
    改动里唯一被删除的代码就是第 1 条修的那两处 `series_read_qc`/`read_qc` 死引用；
    `BIOMEDPARSE_CARD`、`VS_SEG_CARD` 两张真实证据卡的字段值自始至终一个字节没有被改动过——
    不是靠悄悄调整真实卡片的证据状态让新闸门"看起来"通过。
  - 逐条核对四个新增闸门与既有闸门的严格程度关系，确认没有反向放宽任何已生效的判定：
    `candidate_mask_admission`（候选复核，最低门槛）不读 automatic_execution/product_execution，
    不要求 patient/negative/OOD，但仍要求 weights/code/license/input_contract/task_compatibility
    非空且处于 VERIFIED 或 HISTORICAL；`execution_request_admission`（能否提出执行申请，中间门槛）
    只看 weights/input_contract/patient_validation/cpu_budget 且要求严格 VERIFIED；
    `product_execution_admission`（能否被批准执行，最高门槛，本轮未改动）要求全部工程+产品证据
    皆为 VERIFIED 且两个执行标记为真。三层门槛递增、互相独立，`lesion_type_admission`（瘤种声明，
    最高层）仍然只能通过 `product_execution_admission` 再叠加 type_region_binding，
    `candidate_mask_provenance` 的返回值经代码审查确认按构造不含任何 type/tumor_type 字段。
  - 现场验证"候选 mask 不构成隐式采用"这条最容易出安全问题的断言：在 VS-SEG-002 真实数据上
    调用 `add_ai_result` 接入候选 mask 后，`working_mask`/`active_layer_id` 均未变化，`adopt_ai_result`
    是一次独立操作，`undo` 之后候选版本本身完整保留——与测试断言逐项吻合，不是只看通过数字。
  - 核对 `evidence_card_completeness` 对 BIOMEDPARSE_CARD 缺 `source_identity` 的处理：确认本轮
    没有为它编造一个 `ModelSourceIdentity` 来让审计"好看"，如实报告缺口，这是正确的做法——
    补一个未经独立核实的来源身份等于伪造溯源证据。
  - 流程节奏问题（提出但不影响本次通过判定）：我在里程碑 D 上一轮交接里明确写的是
    "本轮明确不做"执行包第 2-4 条，只授权第 1 条；但工作会话在完成第 1 条反馈包提交后，
    没有等审查介入就依次自行认领了第 2、3、4 条（每条都各自提交了反馈包，但连续四条之间
    没有真正的审查检查点）。这次内容本身没有问题——每一步都新增测试、都保持 fail-closed、
    都没有让两个真实候选提前通过任何一层——所以本轮不要求回退，但记录在案：
    下一次交接如果又明确写"本轮只做 X"，请按字面止步于 X，出现新决策点就停下来交回复核，
    不要自行连续认领后续条目。
  - 未发现：病例身份混淆、把显示效果当数据正确性、放宽已生效的模型或医学功能边界、
    删检查绕过失败、伪造模型证据或运行结果。
  - 结论：里程碑 D 验收句（无模型包、缺少序列证据、空间身份不匹配、伪造结果均会被拒绝；
    不产生诊断或效能声明）已被四个新测试文件 + 既有 6 项准入测试，在仓库仅有的两个真实候选
    （BiomedParse、VS-SEG）上逐层验证——两者在全部四层门槛（候选复核/证据完整性审计/执行申请/
    执行批准）下都被拒绝，没有一层是侥幸通过，字面达成，予以通过。四个里程碑（A/B/C/D）
    的第一轮工作至此全部完成。

Decision requested（三项均不阻塞已完成的验收，等用户方便时逐一批复；在收到之前不建议再新增
没有真实模型/真实调用方的候选接入代码）：
  1. 【里程碑 C 遗留】3D 视角是否要随当前切片/病灶选中位置联动、具体定义是什么
     （现状：`show_mesh3d` 视角固定 30°/20°，与 `current_3d_pos` 无连接）。
  2. 【里程碑 D 第 2 条】`candidate_mask_admission` 对 weights/code 等字段接受
     `EvidenceState.HISTORICAL`（不只 VERIFIED）是否要收紧为只接受 VERIFIED。复核时核实过：
     这个口径目前对仓库里两个真实候选都不产生任何实际影响——BIOMEDPARSE_CARD 即使
     weights/code 是 HISTORICAL 也会因 license=NOT_ESTABLISHED、task_compatibility=
     NOT_ESTABLISHED 被拒；VS_SEG_CARD 的 weights 本身就是 PENDING（连 HISTORICAL 都不是）。
     即收紧与否今天都不会让任何候选通过，可以不急着定。
  3. 【里程碑 D 第 4 条】是否需要为"执行申请"本身设计正式模板/文档格式。本轮判断：两个真实
     候选都过不了 `execution_request_admission`，没有真实场景驱动模板形状，建议等某个候选真的
     四项证据（weights/input_contract/patient_validation/cpu_budget）齐备时再设计，不预先造。

Next task: 无（不是等待用户转述批准，是决策 1-3 本身需要用户对产品行为/证据口径拍板，不是
  MUI 工作可以单方面判断的范围）。回归基线：四个里程碑累计 245 项里程碑专属测试 + 既有全套
  1487 项测试，建议作为此后任何改动的强制门槛（须继续保持全绿），任何新一轮工作开始前先跑一遍
  确认基线仍然成立。
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

## 当前交接（用户已批复两项开放决策）

```text
Feedback for review
Commit: 262a2b4
Scope completed: 用户对上一轮两项开放决策直接批复：(1) 里程碑 C 遗留的"3D 视角随切片联动"
  明确不做；(2) `candidate_mask_admission` 收紧为只接受 `EvidenceState.VERIFIED`，不再接受
  `HISTORICAL`。本轮只落地第 (2) 项代码改动，第 (1) 项是"不做"，未产生任何改动。
  收紧后对两个真实候选的影响：BIOMEDPARSE_CARD 新增在 weights/code 上被拒（此前只因
  license/task_compatibility 被拒），VS_SEG_CARD 拒绝集合不变（其 weights/input_contract/
  task_compatibility 本来就是 PENDING，不是 HISTORICAL）——两者此前已被拒绝，收紧没有制造新的
  拒绝，只是让 BiomedParse 的拒绝理由更严格、更准确。
Files changed:
  - tumor_model_admission.py（`candidate_mask_admission` 内一行判定条件收窄 + docstring 说明）
  - tests/test_milestone_d_candidate_mask_admission.py（新增 5 项回归，把"仅 HISTORICAL 时拒绝"
    钉死，防止以后被悄悄放宽回去而没有测试报错）
Validation（逐条重跑非缓存结果）:
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_a_mri_workflow.py` → 38/38 通过
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_b_annotation_workflow.py` → 76/76 通过
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_c_workspace_continuity.py` → 44/44 通过
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_d_vs_t1_source_qualification.py` → 12/12 通过
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_d_candidate_mask_admission.py`
    → 36/36 通过（比上一轮多 5 项：HISTORICAL-only 逐字段拒绝回归）
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_d_evidence_card_completeness.py` → 14/14 通过
  - `/opt/miniconda3/envs/dicom_gui/bin/python tests/test_milestone_d_execution_request_admission.py` → 20/20 通过
  - `SKIP_REAL_DATA=1 /opt/miniconda3/envs/dicom_gui/bin/python tests/test_gui.py` → 1487/1487 全绿（保持）
  - `/opt/miniconda3/envs/dicom_gui/bin/python -m unittest tests.test_tumor_model_admission -v` → 6/6 通过
  - `ruff check tumor_model_admission.py tests/test_milestone_d_candidate_mask_admission.py`
    → All checks passed；`git diff --check` → 无残留
Known limits / failures: 无新增。上一轮交接里提到的"流程节奏"提醒已收到——本轮严格按用户逐条
  下达的指示执行，未自行连续认领超出当次指示范围的条目。
Decision requested: 无。三项开放决策中的两项（C item 4、HISTORICAL 口径）已批复完毕；第三项
  （执行申请模板是否需要）仍待用户方便时回复，不阻塞任何已完成验收。
Next safe task: 四个里程碑（A/B/C/D）第一轮工作、复核和用户决策均已完成闭环。下一步取决于用户：
  若要继续，建议方向是里程碑 B/D 已识别但明确排在范围外的项目（例如"执行申请模板"的决定，或
  annotation_tumor_plan.md 里 R2 及以后的模型研究方向）；若无新指示，本会话保持等待，不主动新增
  未经明确授权的产品改动。
```

## 当前交接（用户指示"进入 R2 模型研究方向"，已按"只做纯文字研究"完成一轮）

```text
Feedback for review
Commit: f144b1d
Scope completed: 用户选择"执行申请模板暂时不做，进入 R2 模型研究方向"，并在确认范围时明确选择
  "只做纯文字/公开资料研究"（不下载、不装依赖、不跑代码、不做任何需要本机凭据的鉴权请求）。
  本轮只用 WebFetch/WebSearch 重新核对了 docs/annotation_tumor_plan.md 里两条仍活跃的研究线索
  （Prima、EfficientNetB1+U-Net/BRISC 2025），未碰产品代码，未新增/修改任何 ModelAdmissionCard。
  这不是里程碑 A/B/C/D 范围内的任务，是用户直接指定的独立研究任务。
Files changed:
  - docs/annotation_tumor_plan.md（追加一个带日期的新研究小节，未改动任何既有段落/结论）
Validation: 文档改动不影响产品代码，仍复跑了 `SKIP_REAL_DATA=1
  /opt/miniconda3/envs/dicom_gui/bin/python tests/test_gui.py` → 1487/1487 全绿（保持不变）；
  `git diff --check` → 无残留。
Known limits / failures:
  - Prima 论文 v2（此前只查过 v1）明确写权重+代码均 MIT、仅限研究用途——但这只是论文自述，
    本轮没有下载任何文件去核实分发的权重实际许可文本与论文声明是否一致。
  - Prima 的患者级验证证据仍不满足 R3 门槛：训练/测试划分是同机构按时间切分（29,435 名患者，
    测试窗口在训练截止后一年），不是跨机构的患者级独立验证，且没有 OOD/拒绝机制；输出是
    study-level 52 标签多标签向量，不含病灶级定位。结论：G2–G5 的推荐排序不变，R3 仍 NO-GO。
  - EfficientNetB1+U-Net、BRISC 2025 两条分类线索原地复核：仍无官方可下载权重，结论与
    2026-09-08 记录一致；额外发现两个第三方 BRISC 分割（非分类）仓库，判断为不解决"分类组件"
    这个具体缺口，未纳入候选池（候选池上限已在 R1 用满）。
  - 没有做的事，如实记录：未重新核实 NeuroVFM 的 HuggingFace gated-repo 访问状态（那需要本机
    凭据发起鉴权请求，超出本轮"纯文字研究"范围）；未下载 Prima 任何权重文件；未新增候选、
    未触碰 tumor_model_admission.py。
Decision requested: 无。上一轮遗留的唯一开放决策（执行申请模板是否需要）已由用户明确选择
  "暂时不做"，本次不重复提问。
Next safe task: 若要继续模型研究方向，两条明确的下一步都已写在 annotation_tumor_plan.md 新增小节
  末尾：(1) NeuroVFM 待用户对齐 HF 账号权限后再复查访问状态（需要本机凭据鉴权，超出纯文字研究
  范围，需用户另行明确授权）；(2) Prima 若要继续，需要下载权重核实许可声明与实际分发文件是否
  一致、并寻找跨机构独立患者级验证证据（同样需要下载/联系官方，超出本轮范围）。若无新指示，
  本会话保持等待，不主动下载模型、安装依赖或运行推理。
```

## 当前交接（NeuroVFM 访问状态复查：门已开，权重仍未下载）

```text
Feedback for review
Commit: 97895f6
Scope completed: 用户指示"NeuroVFM 账号权限对齐后再复查访问状态"。用本机既有 huggingface_hub
  凭据（账号 sunce764，非本轮新配置）对两个固定 revision 只请求 config.json（不请求权重），
  结果：两个 gated repo 的访问都已获批（此前 2026-09-08 是 403/GatedRepoError）。
Files changed:
  - docs/annotation_tumor_plan.md（追加一节记录访问状态变化与两份 config.json 的架构信息）
Validation: `SKIP_REAL_DATA=1 /opt/miniconda3/envs/dicom_gui/bin/python tests/test_gui.py`
  → 1487/1487 全绿（保持不变，文档改动不影响产品代码）；`git diff --check` → 无残留。
Known limits / failures:
  - 只取了两份 config.json（385+212 字节），完全没有下载 pytorch_model.bin 权重本体
    （合计约 290MB）；没有核实权重文件哈希、没有核实权重许可条款文本、没有安装任何推理依赖、
    没有做任何前向计算。"访问已获批"只表示门开了，不表示 CPU 适配、患者级验证或产品接入
    往前推进了一步。
  - config 内容确认了两点此前只是推测的细节：encoder 是 ViT-Base（depth 12/heads 12/768 维），
    体素 patch embed 用 fused_bias_fc=true——2026-09-08"NeuroVFM CPU适配范围审计"里对
    FusedDense/FusedBias 的顾虑现在有了具体配置依据；dx-mri 头输出 74 维，与 Prima 的 52 维
    诊断标签体系不同，两个模型不能互相替代或直接比较指标。
Decision requested: 是否要继续推进到"下载 290MB 权重文件并核对哈希"这一步？这会撞到"不下载
  模型"的硬边界，需要用户单独、明确地为这一具体下载授权（不能从"账号权限已对齐"推导出
  "可以下载权重"）。在收到这个单独授权前，本会话不会下载任何权重文件、不安装新依赖、
  不做任何前向推理。
Next safe task: 等待用户对上面那个具体决策的答复。若批准下载，需要先明确资源上限（沿用
  2026-09-08 记录里的默认 4 threads / 15 分钟 / 12GiB 采样上限，或用户给新的数值）以及
  下载后的第一步是只做哈希/文件大小核对还是直接进入 CPU 适配原型验证。
```

## 当前交接（NeuroVFM 权重已下载+哈希；许可条款是产品接入的具体障碍）

```text
Feedback for review
Commit: d10b893
Scope completed: 用户明确指示"下载"。下载了两个固定 revision 的 pytorch_model.bin（encoder
  286,576,042 字节、dx-mri 3,789,726 字节，与 2026-09-08 记录的字节数完全一致），首次算出
  真实 SHA256（encoder: 744cf058…8fc7；dx-mri: e3db6eee…2492b）。只做了下载+哈希+读取纯文本
  README.md，没有安装新依赖、没有 torch.load、没有构造模型、没有任何前向推理——按"下载"这个
  指示的字面范围止步，没有自行推进到"验证推理"。
Files changed:
  - docs/annotation_tumor_plan.md（追加一节记录哈希结果与许可发现）
  - 两个权重文件本身在本机全局 HuggingFace 缓存（~/.cache/huggingface/hub/），已确认不在本
    仓库工作树内，不会被 git 跟踪或提交。
Validation: `SKIP_REAL_DATA=1 /opt/miniconda3/envs/dicom_gui/bin/python tests/test_gui.py`
  → 1487/1487 全绿（保持不变）；`git diff --check` → 无残留；`find . -name pytorch_model.bin`
  → 空（确认权重不在项目目录里）。
Known limits / failures:
  - **关键发现，需要决策**：两个仓库的官方 README 都写明权重许可是 CC-BY-NC-SA-4.0
    （"Non-Commercial Research Use"），代码是 MIT。本项目 `pyproject.toml` 声明
    `Proprietary — All rights reserved`——如果要把 NeuroVFM 接入 MUI 产品，这个 Non-Commercial
    条款会直接冲突，除非官方另行给商用许可。这不是新的许可问题类别（CLIP-Driven 的
    CC BY-NC-ND 之前就标过同类顾虑），但这次是对着真实下载、真实算出哈希的文件确认的，
    不再是纯理论顾虑。
  - 出处已升级为同行评审期刊（Nature Medicine，此前只查过 GitHub/HF 页面）：训练数据
    218,882 例 MRI（单一机构，密歇根大学健康系统），诊断头是 74 项专家定义诊断本体的
    modified AB-MIL 架构。仍是同机构队列，没有跨机构独立患者级验证证据。
  - 没有做的事：没有验证权重内部键结构是否与 2026-09-08 CPU 适配审计假设的架构完全对应；
    没有查论文全文是否有更详细的验证设计；没有把这两个文件路径接入产品代码或
    `tumor_model_admission.py` 的任何证据卡（仍是零改动）。
Decision requested: 这份 Non-Commercial 许可对 MUI 的商业模式是否可接受？如果不可接受（或
  没有另行获取商用许可的渠道），继续投入 CPU 适配原型或推理验证的技术工作在许可层面就走不通，
  建议先在这里止步，把资源转向别的候选或明确等待商用许可澄清；如果可接受或已经在协商商用许可，
  再决定是否继续做 2026-09-08 记录里规划的 CPU 适配原型验证（那一步会需要新装依赖、构造模型、
  执行前向计算，届时会撞到"不训练/不用 GPU"之外的"是否可以本地推理"这个新边界，需要再单独确认）。
Next safe task: 等用户对上面的许可决策表态。在收到之前，本会话不会安装新依赖、不会构造/加载
  模型对象、不会执行任何推理，不会把这两个权重文件接入任何产品代码路径。
```

## 当前交接（许可障碍已解除；CPU 推理验证仍待单独确认）

```text
Feedback for review
Commit: c50fbc8
Scope completed: 用户明确答复"我们不商用"，解除了上一轮标出的 NeuroVFM 权重许可障碍
（CC-BY-NC-SA-4.0 Non-Commercial 与产品 Proprietary 声明的冲突）。
Files changed:
  - docs/annotation_tumor_plan.md（追加两句：记录用户答复，并写明两条限定——这只是用途确认
    不等于改写 pyproject.toml 的许可声明；许可障碍解除不等于自动获得装依赖/跑推理的授权）。
Validation: 纯文档改动，未跑产品回归（上一轮已确认 1487/1487，本次未改任何产品代码或依赖）。
Known limits / failures: 无新增。
Decision requested: 是否继续推进到 NeuroVFM 的 CPU 适配原型验证？这一步会需要：
  安装 torch 之外的模型相关依赖（若当前 dicom_gui 环境缺失）、用固定源码构造模型对象、
  执行至少一次前向计算（哪怕是随机小配置的原型验证，性质上仍是"在本机运行第三方模型代码"）。
  这与"下载文件"是不同类别的动作，尚未获得授权。2026-09-08 的记录里已经有一个类似原型
  （`cpu_prototype.py`，独立 AST 载入官方类、替换 FusedDense/FusedMLP 为等价 Linear 实现）
  可参考，但那次是在合成小型配置上做的，从未加载过真实下载的这两个 checkpoint。
Next safe task: 等用户表态是否继续 CPU 适配/推理验证；若继续，需要先确认资源上限
  （沿用默认 4 threads / 15 分钟 / 12GiB，或新数值）以及范围边界（先做"权重键名/shape 与
  config 声明的架构逐项核对"这种只读检查，还是直接构造模型做前向）。
```
