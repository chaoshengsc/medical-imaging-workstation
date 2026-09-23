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
Milestone: A/B/C/D 工程验收已通过；NeuroVFM 固定权重的两例 DICOM→官方预处理→CPU 编码器→检查级分类头技术链路已跑通。自动肿瘤分割与逐病灶分类未完成。
Base commit: c9d7150（VS-Seg T1 权重包完整性核验）
Writer: Codex；更新模型准入卡中的权重证据并加定向门禁测试，未改模型运行路径或 UI。

Verified 2026-09-23:
  - A/B/C/D 基线见上一提交 80be4cb；本轮没有修改其产品代码，未把旧 PASS 当新性能证据。
  - 固定源码 MLNeurosurg/neurovfm@9240021，增补归一化模块后 15 个文件的 Git blob 摘要通过；两个已缓存权重的 SHA256 与 d10b893 一致。
  - 静态审计：encoder 136 个张量、MRI 诊断头 16 个张量，键名/shape 与固定 config 精确一致；MRI 标签 74 个唯一项；9 项检查全通过。
  - PyTorch 2.5.1、4 CPU 线程、weights_only=True/mmap=True 成功读取两份 state dict，加载元数据逐张量一致；没有构造编码器。
  - 官方 ClassifyThenAggregate 在 CPU 替换 FusedDense 和 segment_csr 后，真实权重 strict=True 加载，用合成 patch 特征输出 [2,74]；两段注意力和误差 1.19e-7，分批与单独运行最大差 0；缺失键被拒绝。
  - 固定官方 VisionTransformer 类体在隔离 CPU namespace 中替换 fused dense/MLP/残差 norm 后，真实编码器权重 strict=True 加载；合成 8 patch 输出 [8,768]，接诊断头得到检查级 [2,74]；两序列合批与分开运行最大差 0，故意缺少 norm.bias 被拒绝。
  - VS-SEG-002/003 各 120 帧单一 MR Series，SimpleITK 3D 读取与 DICOM 患者空间逐片原点最大差 9.33e-14/2.05e-13 mm；混序列、重复 SOP、缺片反例被拒绝。
  - 两例真实 T1 经固定官方预处理及归一化，分别生成 335/283 个 token，CPU 编码器+诊断头输出有限的检查级 [1,74] 分数；前向各约 1.0–1.3 秒、进程峰值 RSS 约 2.4–2.5 GB（仅此本机两例技术测量）。
  - 上一交接时，KCL VS_Seg T1 官方约 34.4 MB 权重包仍未下载；本轮用户明确授权后已下载并完成归档完整性核验，细节见 `docs/annotation_tumor_plan.md` 的“同日 T1 权重包下载与完整性核验”。作者固定 split 为 176/20/46，vs_gk_2/3 在训练组；恢复的 VS-SEG-002/003 在本项目准入卡中按训练重叠隔离。本机仍没有可用参考 mask，作者测试入口依赖 label，不可原样用于无真值推理。
  - 权重包官方大小/MD5 匹配，本地 ZIP SHA-256、CRC 与内部 best/last checkpoint SHA-256 已记录；`Annotation_Projects/vs-seg-t1-20260923/` 被 `.gitignore` 忽略。PyTorch 2.13.0 `weights_only=True` 安全读取 best checkpoint 成功；256 个张量条目，首层 shape 与固定上游配置一致。两套本机 Python 均无 MONAI，未构造模型、执行 forward 或生成 mask；准入卡的 `weights` 仍保持 PENDING，直至模型可严格加载。
  - TCIA VS-MC-RC2 提供约 6 GB 的外域 NIfTI/T1CE mask 候选，但当前只确认资料与 Aspera 传输要求；未安装插件、未下载或证明训练无交叉。
  - 静态审计恶意 GLOBAL、未知 opcode、非张量顶层、错误摘要 4 个反例测试通过。具体命令与忽略目录下的 JSON 结果见 docs/annotation_tumor_plan.md 的 2026-09-23 节。

Limits:
  - 两例整例技术运行已发生，但 CPU 替换与 GPU fused kernel 尚未数值对照；病例已用于联调，不是独立效能测试。没有类型准确性或诊断结论。
  - 官方 StudyPreprocessor.load_study 对直接传入的 DICOM 目录逐文件枚举；本轮用已证唯一序列目录的单元素列表入口规避，产品通用输入适配尚未实现。
  - NeuroVFM 只有检查级标签，不生成 mask，也不能自动把类型绑定至某个病灶；产品未接入其权重。
  - A/B 仅有 Undo 无 Redo；C 的主观 UI 验收仍不全；D 的准入拒绝门不是模型效能证明。
  - KCL 权重包身份与字节完整性已验证，best checkpoint 仅做 safe tensor parse 和首层 shape 对照；全网 strict load、CPU/空间往返、无标签输入和患者级效果均未验证，所以研究/产品准入卡的 `weights` 仍为 PENDING。官方推理脚本使用标签做评分/导出元数据；产品侧 no-label adapter 仍未实现。下载包内的训练/测试日志与示例图不构成本项目独立验证。
  - 当前非商用用途已确认；未来若分发权重或改变用途，仍核对许可、署名和分发条件。没有 push。

Feedback for review
Commit: 本提交（以 git log -1 的实际哈希为准）
Scope completed: 在用户明确授权后下载 KCL VS_Seg T1 权重包，核对官方文件身份、压缩包完整性和内部 checkpoint 摘要；安全解析 best checkpoint，保留准入卡的 weights=PENDING，避免将本机忽略文件状态硬编码成通用可用性。
Files changed: `docs/annotation_tumor_plan.md`、`docs/AGENT_SYNC.md`。权重仅保存在忽略目录 `Annotation_Projects/vs-seg-t1-20260923/`，不进入提交。
Validation: `stat -f '%z' Annotation_Projects/vs-seg-t1-20260923/UNet2d5_Att_Hard_T1_final.zip` → 34377805；`md5 -q Annotation_Projects/vs-seg-t1-20260923/UNet2d5_Att_Hard_T1_final.zip` → 官方 MD5 匹配；`shasum -a 256 Annotation_Projects/vs-seg-t1-20260923/UNet2d5_Att_Hard_T1_final.zip` → ZIP SHA-256 已记录；Python `ZipFile.testzip()` → `None`（所有成员 CRC 通过）；流式计算两个内部 checkpoint SHA-256；`torch.load(..., weights_only=True)` → 256 项纯 tensor OrderedDict，首层为 `(16, 1, 3, 3, 1)`；`python -m unittest tests.test_tumor_model_admission -v` → 6/6 通过；`git check-ignore -v Annotation_Projects/vs-seg-t1-20260923/UNet2d5_Att_Hard_T1_final.zip` → 被 `Annotation_Projects/` 忽略；`git diff --check` → 通过。未运行完整 GUI 测试（产品 UI 未改）。
Known limits / failures: MONAI 不在两个现有 Python 环境中；未安装依赖或模型包、未进行全网 strict load/forward、无标签 CPU 预处理、mask 空间往返、CPU 资源与患者级效果均未验证。当前两例 VS 病例在作者训练 split 中，只能用于工程调试。
Decision requested: none。
Next safe task: 静态审阅固定上游 requirements 和本机现有环境，判断严格加载能否在不安装依赖的前提下完成；同步设计无标签输入与原始 DICOM 空间往返方案，并继续取得作者 test 或训练排除可证明的外部参考 mask。当前两套 Python 均缺 MONAI，不下载/安装依赖或运行模型。VS-SEG-002/003 只作工程调试。NeuroVFM 仍是检查级线索，不能绑定具体病灶；没有病灶级分类证据时保留人工/候选 mask 工作流。
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
