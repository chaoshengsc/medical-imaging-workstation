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
Milestone: A/B/C/D 工程验收已通过；NeuroVFM 固定权重的两例 DICOM→官方预处理→CPU 编码器→检查级分类头技术链路已跑通。KCL VS_Seg 作者 test 参考数据已取得并临时栅格化；自动肿瘤分割与逐病灶分类仍未完成。
Base commit: f220cf5（VS-Seg T1 checkpoint 检查限制）
Writer: Codex；本轮完成作者 test 数据映射、DICOM 配对和临时参考 mask 几何检查，仅更新研究记录及交接文档，未改产品代码或 UI。

Verified 2026-09-23:
  - A/B/C/D 基线见上一提交 80be4cb；本轮没有修改其产品代码，未把旧 PASS 当新性能证据。
  - 固定源码 MLNeurosurg/neurovfm@9240021，增补归一化模块后 15 个文件的 Git blob 摘要通过；两个已缓存权重的 SHA256 与 d10b893 一致。
  - 静态审计：encoder 136 个张量、MRI 诊断头 16 个张量，键名/shape 与固定 config 精确一致；MRI 标签 74 个唯一项；9 项检查全通过。
  - PyTorch 2.5.1、4 CPU 线程、weights_only=True/mmap=True 成功读取两份 state dict，加载元数据逐张量一致；没有构造编码器。
  - 官方 ClassifyThenAggregate 在 CPU 替换 FusedDense 和 segment_csr 后，真实权重 strict=True 加载，用合成 patch 特征输出 [2,74]；两段注意力和误差 1.19e-7，分批与单独运行最大差 0；缺失键被拒绝。
  - 固定官方 VisionTransformer 类体在隔离 CPU namespace 中替换 fused dense/MLP/残差 norm 后，真实编码器权重 strict=True 加载；合成 8 patch 输出 [8,768]，接诊断头得到检查级 [2,74]；两序列合批与分开运行最大差 0，故意缺少 norm.bias 被拒绝。
  - VS-SEG-002/003 各 120 帧单一 MR Series，SimpleITK 3D 读取与 DICOM 患者空间逐片原点最大差 9.33e-14/2.05e-13 mm；混序列、重复 SOP、缺片反例被拒绝。
  - 两例真实 T1 经固定官方预处理及归一化，分别生成 335/283 个 token，CPU 编码器+诊断头输出有限的检查级 [1,74] 分数；前向各约 1.0–1.3 秒、进程峰值 RSS 约 2.4–2.5 GB（仅此本机两例技术测量）。
  - 作者固定 split 为 176/20/46，vs_gk_2/3 在训练组；恢复的 VS-SEG-002/003 在本项目准入卡中按训练重叠隔离。作者 test 的 46 例 T1 与各自两份候选 RTSTRUCT 已下载：138/138 series，TCIA API 解压数据量 2,985,054,416 bytes，逐文件 MD5/ZIP CRC/实例数通过。DICOM 引用核对 46/46 唯一配对成功，原始 ROI 名保留（TV 39、AN 7）。首轮 `rt-utils 1.2.7` 输出后来查明面内行列轴转置错误，46 份旧 mask 已隔离在 `rtutils-reference-masks-axis-transposed-invalid/`，标记为无效。修正为 transpose(2,0,1) 后重建 46 份 NIfTI，并用预装 VTK 9.6.0 按物理轮廓独立栅格复核：占用切片逐例相同，几何实现 Dice 中位数 0.96543、范围 0.92758–0.98275；差异是边界填充离散化差异，不是模型分数。Slicer/SlicerRT 当前安装为 x86_64；官方稳定版和预览版 macOS 下载当前均 amd64，arm64 build 指南标记为 work-in-progress。官方 Debug 构建需超过 20 GB，当前仅余约 26 GiB，不安全启动。证据和脚本在忽略目录 `Annotation_Projects/vs-seg-test-20260923/`，不进 Git。
  - 权重包官方大小/MD5 匹配，本地 ZIP SHA-256、CRC 与内部 best/last checkpoint SHA-256 已记录；`Annotation_Projects/vs-seg-t1-20260923/` 被 `.gitignore` 忽略。PyTorch 2.13.0 `weights_only=True` 安全读取 best checkpoint 成功；256 个张量条目，首层 shape 与固定上游配置一致。现有 base（torch 2.13）、boa（torch 2.5.1）均无 MONAI；denoise（torch 2.8/MONAI 1.5）新进程因重复 `libomp.dylib` abort；dicom_gui（torch 2.11）无 MONAI，当前不可构造官方网络。作者固定 requirements 为 torch 1.6/MONAI 0.4；静态评估完成时尚未安装依赖、未严格加载或执行 forward。
  - 静态依赖可行性（2026-09-23）：本轮只读重查 boa 为 Python 3.10.20 / arm64、torch 2.5.1、NumPy 1.26.4；MONAI、natsort、TensorBoard 缺失，torchvision、pydicom、nibabel、matplotlib 已有。固定上游 requirements.txt 要求 torch~=1.6.0、MONAI==0.4.0、torchvision~=0.7.0 等；作者网络本身主要用 PyTorch 原生卷积/归一化层及 MONAI 的 Norm/Act factory、SkipConnection、same_padding，完整 VSparams.py 另会拉入未安装的 natsort/TensorBoard，但可由最小加载器绕开。MONAI 0.4.0 官方 PyPI wheel 是 350,941-byte 的纯 Python wheel，元数据最低要求 Python>=3.6、torch>=1.5、NumPy>=1.17；现有 boa 满足元数据，但没有证据保证旧 MONAI 与 torch 2.5.1 组合兼容。官方 Apple Silicon 原生 PyTorch 包从 1.12 才以 prototype 形式出现，故作者锁定 torch 1.6 不能作为本机原样 arm64 环境。预装 denoise 中 MONAI 1.5.0 源码虽保留网络 factory/skip/same_padding，但缺少作者直接导入的 monai.utils.aliases 旧路径，且该环境 torch 导入会因重复 libomp abort；不能直接复用。静态评估完成时未创建环境、未下载/安装 MONAI、未加载 checkpoint 或运行模型。详见 docs/annotation_tumor_plan.md 2026-09-23 静态依赖段。
  - 依赖 wheel 下载（2026-09-23）：用户允许下载后，从官方 PyPI 下载 `monai-0.4.0-202012151415-py3-none-any.whl` 至 Git 忽略目录 `Annotation_Projects/vs-seg-t1-20260923/dependency-source/`；大小 350,941 bytes，SHA-256 `da0395de904acdfeb261dbbe46d6fecadfc274991385604dcf5e5b49a483242e` 与 PyPI 元数据一致，137 个归档成员路径检查无绝对路径或 `..`。下载阶段 wheel 未解包；之后已在一次性忽略目录 venv 中离线安装。MONAI 官方安全公告 [GHSA-x6ww-pf9m-m73m](https://github.com/Project-MONAI/MONAI/security/advisories/GHSA-x6ww-pf9m-m73m) 标明 <=1.5.0 版本存在 bundle ZIP 路径穿越漏洞；本次已获准探针仅在一次性隔离环境中导入网络层，未调用 bundle 下载/解压 API，也未处理外部压缩包。wheel 下载本身不证明兼容；固定网络 strict-load 结果见下一条。
  - VS-Seg strict-load 探针（2026-09-23）：固定 KCL commit 的 3 个网络源码文件逐文件核对 Git blob SHA；按 VSparams.py 的作者配置构造 UNet2d5_spvPA。PyTorch 2.5.1 `weights_only=True` 安全读取已校验 checkpoint，以 `strict=True` 完整加载 256 个张量（3,455,790 个元素），missing/unexpected keys 均为空。运行环境 Python 3.10.20 arm64、CPU 单线程、Torch 2.5.1、MONAI 0.4.0、NumPy 1.26.4。裸 MONAI import 因 NumPy 移除 `np.bool` 失败；只在探针进程临时设置 `np.bool = bool` 后成功，不改包或产品代码。未执行 forward、未读取患者影像。报告与源码清单在忽略目录 `Annotation_Projects/vs-seg-t1-20260923/cpu-strict-load-20260923/`；VS_SEG_CARD 的 `weights` 已标为 VERIFIED，但其余运行和验证门仍关闭。
  - VS-Seg 合成 CPU shape 冒烟（2026-09-23）：固定 KCL 网络及 T1 checkpoint 对确定性合成输入 `[1,1,384,384,64]` 执行一次全精度、单线程前向，输出 `[1,2,384,384,64]` 且 logits 全有限；模型前向 65.88 秒。0.5 秒采样的进程组峰值 RSS 为 11.73 GiB，低于 12 GiB 终止线但余量很小；采样不是硬隔离，可能低估瞬时峰值。未读取病例、未计算分割指标。初次 worker 在成功输出后因异常捕获范围过宽多打印一条 `SystemExit(0)` 诊断，返回码为 0 且最终 JSON 为 PASS；随后已修正脚本处理，未为该日志问题重复高内存前向。报告、脚本与固定 VSparams 源码均在忽略目录。此单 patch 冒烟不够把 `cpu_budget` 标为 VERIFIED。
  - VS-Seg no-label adapter（2026-09-23）：新增 `vs_seg_t1_adapter.py`，输入必须先通过固定 `VST1Request` / 来源资格门；执行产品 `SeriesVolume zyx → xyz`、LPS→RAS、官方 MONAI 0.4 RAS orientation、含零背景的全卷 NormalizeIntensity，并保留来源/request digest 与 affine。二值 mask inverse 要求同一来源、shape 与 0/1 值域，并返回原始 zyx/LPS；不加载权重、不运行网络、不接入人工层。5 种合成朝向下与 MONAI Orientation/Normalize 数组逐 bit 一致、affine `atol=1e-7`，结果见忽略目录 `product-adapter-monai-crosscheck.json`。另对作者 test split 的 5680 张 MR DICOM 仅读取头信息，46/46 T1 序列的 RescaleSlope/Intercept 均为恒等变换；产品 MR `SeriesVolume` 保留 stored values，故适配器只接受恒等 rescale，非恒等、空值或非有限 metadata 均 fail-closed。KCL 官方 DICOM→NIfTI 路径经 Slicer/ITK，ITK GDCM 会应用 RescaleSlope/Intercept，但当前 x86_64 Slicer 不能在 arm64 主机原生运行，非恒等 rescale 尚未有 Slicer 逐体素对照，不宣称支持。`tests/test_vs_seg_t1_adapter.py` 5/5 通过且纳入统一 GUI runner。首轮对照抓到 affine 更新但像素漏翻，已修复并由逐体素映射断言覆盖。`VS_SEG_CARD.input_contract` 标为工程变换合同 VERIFIED；不表示真实序列自动识别或模型效果已验证。产品执行 gate 仍独立 fail closed。
  - TCIA VS-MC-RC2 提供约 6 GB 的外域 NIfTI/T1CE mask 候选，但当前只确认资料与 Aspera 传输要求；未安装插件、未下载或证明训练无交叉。
  - 静态审计恶意 GLOBAL、未知 opcode、非张量顶层、错误摘要 4 个反例测试通过。具体命令与忽略目录下的 JSON 结果见 docs/annotation_tumor_plan.md 的 2026-09-23 节。

Limits:
  - 两例整例技术运行已发生，但 CPU 替换与 GPU fused kernel 尚未数值对照；病例已用于联调，不是独立效能测试。没有类型准确性或诊断结论。
  - 官方 StudyPreprocessor.load_study 对直接传入的 DICOM 目录逐文件枚举；本轮用已证唯一序列目录的单元素列表入口规避，产品通用输入适配尚未实现。
  - NeuroVFM 只有检查级标签，不生成 mask，也不能自动把类型绑定至某个病灶；产品未接入其权重。
  - A/B 仅有 Undo 无 Redo；C 的主观 UI 验收仍不全；D 的准入拒绝门不是模型效能证明。
  - KCL 权重身份、安全读取与固定网络 `strict=True` 全网加载已验证；MONAI 0.4/NumPy 1.26 仍需仅限探针进程的 `np.bool = bool` 兼容垫片。全尺寸合成 patch 前向 shape 正确但采样峰值接近 12 GiB，不能证明整例 CPU 预算。产品 no-label 预处理和合成空间还原已实现/逐项对照，但目前无隔离模型 worker 或 GUI 接线；完整病例运行、患者级效果、阴性/OOD 验证均未完成。`cpu_budget`、`task_compatibility` 仍 PENDING，患者/阴性/OOD 等准入门未通过，产品执行仍关闭。作者 test 参考 mask 与独立 VTK 物理栅格交叉核对，不等同 SlicerRT 完整 labelmap conversion 的逐体素复现；MONAI 依赖只装在一次性忽略目录环境。没有患者前向或模型 Dice/HD95。
  - 当前非商用用途已确认；未来若分发权重或改变用途，仍核对许可、署名和分发条件。没有 push。

Feedback for review
Commit: 本提交（以 `git log -1` 的实际哈希为准）
Scope completed: 在已核对 KCL 输入约定后，实现来源/序列证据门控的 T1c image-only 适配器及精确 inverse mask 映射；工程输入合同以 5 类合成几何逐项对照 MONAI 0.4 验证后标记 VERIFIED。无权重加载、患者像素输入、前向或 UI 接线。
Files changed: `vs_seg_t1_adapter.py`、`tests/test_vs_seg_t1_adapter.py`、`tests/test_tumor_model_admission.py`、`tests/test_gui.py`、`tumor_model_admission.py`、`pyproject.toml`、`docs/ARCHITECTURE.md`、`docs/annotation_tumor_plan.md`、`docs/AGENT_SYNC.md`。官方 MONAI crosscheck 与 JSON 报告在 Git 忽略目录，不入库。
Validation: 5 种 axial LPS / reversed axial / coronal / sagittal / oblique 合成 `SeriesVolume` 中，产品 adapter 图像与 MONAI 0.4 `Orientation(axcodes=RAS)+NormalizeIntensity(nonzero=False,channel_wise=False)` 逐 bit 一致，affine `atol=1e-7` 一致，恢复的 mask 与 zyx 来源逐体素相等。`/opt/miniconda3/envs/boa/bin/python -m unittest discover -s tests -p 'test_vs_seg_t1_adapter.py' -v`（5/5），同环境 `test_tumor_model_admission.py`（6/6）；`SKIP_REAL_DATA=1 QT_QPA_PLATFORM=offscreen /opt/miniconda3/envs/dicom_gui/bin/python -u tests/test_gui.py`（1488/1488）；`/opt/miniconda3/envs/boa/bin/ruff check vs_seg_t1_adapter.py tests/test_vs_seg_t1_adapter.py tests/test_tumor_model_admission.py tests/test_gui.py tumor_model_admission.py`、`git diff --check`、`py_compile` 均退出 0；依赖与架构 known-bad 模块清单自检通过。
Known limits / failures: 首轮官方方向对照暴露“affine 更新但像素数组未翻转”；已修复并加入每像素 RAS/source 映射断言。输入合同限定为恒等 MR rescale 子集；非恒等 rescale 明确拒绝，尚未通过 Slicer/ITK 实际导入对照。未验证真实序列自动识别、推理输出、整例资源预算或分割效果。模型运行仍被 execution gate 拒绝；没有 push。
Decision requested: 无。
Next safe task: 设计并实现隔离 KCL 模型 worker 的加载、滑窗与结果协议，接收适配器输出并返回绑定同一 SourceBinding 的二值 mask；先用合成输入验证，继续保持产品执行 gate 关闭，不运行患者推理。
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
