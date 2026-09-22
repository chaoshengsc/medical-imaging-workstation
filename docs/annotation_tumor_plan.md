# CT / MRI 标注与肿瘤功能计划

2026-09-09本地版本补记：用户要求先git再继续UI优化，既有CT/MRI工程基础功能已单独保存为本地commit `fe37ed6a72bbd8e52633db1dae71a83d059e0624`，第一轮已验收UI为 `574e9414233d02f26b2c76658e9923b3a397aaf7`。未push，不代表新的远端CI或模型研究结论。下方2026-09-08的“未提交”是当日历史状态；UI后续记录见 [ui_review.md](ui_review.md)。

更新：2026-09-08。代码核查基线：`6619cf5edec75ea1c831f243a9b438ba81064a3d`。

状态：2026-09-08，E0–E5 已完成工程验收及独立复验，当前为未提交的本地工作区。最新复验数据无关层 1342/1342、全套 1467/1467、真实 MRI 交互 21/21、参考显示/候选保存 6/6，证据在 `Annotation_Projects/reaccept-20260908-130954/`。R2 BiomedParse v2 单例 CPU 技术探针已完成，累计三个获准作业、一次实际 forward；依赖和权重位于独立研究目录，未接入产品。R3 自动类型识别准入仍为 NO-GO，R4 未启动；下一步是分类组件与患者级验证证据补齐。最新工程/模型证据核对见 `Annotation_Projects/r2-biomedparse-20260908/goal-completion-audit.json`。下方按日期顺序保留的“未安装／未运行／待批准”是历史状态。本文是唯一计划与候选研究记录，不代替已实施架构、既有实验报告或软著材料。

## 当前结论

- 工程目标是 CT / MRI 的多序列管理、三视图标注编辑、跨次 Undo、原始 AI 与人工结果对照、完整保存恢复和自动记录。
- 工程主要改动在影像/空间数据结构、编辑事务、工程存储。MRI 多序列配准需要独立验证，不能沿用现有二维切片配准并宣称完成。
- 肿瘤目标始终是软件自动找到病灶、分割其范围、给出对应类型预测；用户无需先指定瘤种。现有通用模型有可继续核查的候选，尚无本项目实测通过的完整组合。
- 模型交付边界（用户确认）：最终用户只加载影像并运行推理，无需训练。优先接入现成权重；允许考虑由开发方训练并定版后交付，不代表已授权具体训练作业。固定版本可随软件分发或首次获取，实际分发方式须符合权重许可与访问条件。
- 优先复用现成模型或组合。脑部 MRI、肺部 CT 是比较线索，不是已经锁定的首批支持承诺；不按每个部位预设独立训练项目。
- 后续连续推进到里程碑，聊天只报告重要结论、阻碍和需要额外授权的事项，不再逐项询问可自行决定的设计细节。

## 1. 需求与默认边界

| 项目 | 本次采用的口径 | 状态 |
|---|---|---|
| 三视图编辑 | Axial / Coronal / Sagittal 均可编辑，同一位置的像素标注同步 | 用户明确确认 |
| 影像范围 | 包含 CT 和 MRI | 用户明确确认 |
| 原始结果 | 保留原始 AI 结果；人工修改形成独立工作结果，可对照 | 用户明确确认 |
| Undo | 真正回退操作，与橡皮擦分开；关闭重开后仍可撤销最近编辑 | 用户明确确认 |
| 保存 | 全部已标注切片、结果来源、统计、路径与格式提示 | 用户明确需求 |
| 多序列联动 | 同次 MRI 检查支持联动定位和对应标注查看，空间不可靠时不强行共享 | 按用户要求采用合理默认 |
| Undo 数量 | 最近 20 个已完成操作，随工程持久化；不承诺无限历史 | 默认值，沿用现有步数上限 |
| 模型研究 | 先查统一模型或现成组合；自行训练另行决定 | 用户已同意方向 |

### 输入范围与空间含义

首期实现静态三维 CT、结构 MRI 的载入和编辑；优先覆盖现有 Classic CT 与新增 Classic MR 单帧 DICOM 序列。Enhanced / 多帧 DICOM、动态 MRI、功能 MRI 分析不作为首期验收前提，遇到不支持的存储类型须给出明确原因。不得以排除格式为由把“支持 MRI”写成已经覆盖所有 MRI 数据。模型需要的 NIfTI 由研究适配层处理，保留坐标和来源转换记录。

三视图必须根据真实空间关系构建。均匀网格可通过 voxel-to-patient 变换支持不同方向及斜采集；几何不成立时保留原始切片阅片/允许的原位标注，关闭无法保证准确的重切面编辑，不伪造层距或解剖方向。

**可编辑必须能安全保存恢复。** 新工程将 `source_binding`（来源帧身份与编辑网格）和 `geometry_binding`（患者空间证明）分开。前者按版本绑定 Study/Series UID、有序且唯一的 SOP UID、矩阵尺寸、解码像素身份摘要及存储网格坐标约定；后者记录可证明的方向、位置、间距和几何指纹。缺 IOP/IPP/PixelSpacing 但来源绑定完整时，只允许来源切片的行列坐标标注和像素编辑，并可保存恢复/Undo；不生成缺依据的患者坐标、毫米量或跨面投影。来源身份缺失、重复冲突或无法建立稳定网格时，在编辑入口前禁用并解释，不能等画完才告知无法保存。恢复原位数据验证来源绑定；凡使用患者空间的对象/变换还必须验证几何绑定。旧格式 AI 缓存继续执行原有四项校验，不以新原位模式绕过旧守卫。

“单像素”指来源标注网格中的一个体素，不是屏幕显示像素。缩放、平移、显示插值均不能改变编辑粒度。普通标尺、路径和 ROI 记录创建平面与空间坐标，其他视图显示对应位置或交线；不复制同一个二维图形冒充三维同步。MIP / MinIP / AIP 厚层投影不提供单体素精修，入口提示切回单层。

有效几何下，明确 affine 将来源网格 `(x,y,z)` 映射到 LPS，数组索引仍为 `[z,y,x]`。斜采集显示通过统一平面采样器生成；影像、mask、光标、测距和命中检测共用同一变换。单击先映射到来源连续坐标，再在半开范围 `[-0.5, size-0.5)` 内以 `floor(q+0.5)` 取一个体素，边界外拒绝修改，不能先裁剪到边缘。影像插值不改变标签和编辑网格，标签用 nearest-neighbor；体素量从来源网格计算。`canonical_orientation` 的旧 CT 模型资格不放宽，新显示空间能力另设判据。首期斜采集的厚层投影与尚未适配空间变换的旧 mesh/随访功能明确禁用，已有受支持 CT 路径继续保留；不能沿数组轴投影后贴上患者解剖方向。

不同序列的标注分别绑定来源网格。联动显示可以使用经过验证的变换；不会因切换序列就反复重采样并覆盖来源 mask，也不会把一次编辑默默广播成对多个独立 mask 的修改。同一病灶的不同序列标注可关联同一个 lesion ID。

### 编辑、来源和结果

- 每次按下至松开的笔画、一次点击、一次 ROI 移动/缩放、一次批量删除各算一个操作；无变化不入栈，中途切换编辑上下文取消未完成操作。
- 按下时冻结来源序列、活动图层、平面、位置和视图到体素映射；笔画/ROI 拖动期间，hover 只更新提示，不驱动切层、自动定位或销毁预览的重绘。进入编辑先停止 Cine，显式切换工具/平面/序列或滚轮导航先取消预览再导航，提交后恢复联动。未提交预览与已提交文档分开，保存任务不能读取半笔数据。
- 普通标注和像素编辑共用顺序历史。Undo 恢复受影响标签、置信度/来源状态及对象属性；跨视图/序列撤销自动定位受影响位置。
- 原始 AI 结果只读保存；活动编辑结果可修改。器官标签与病灶实例使用独立图层，允许空间重叠，不用一个标签覆盖另一个来表达肿瘤。
- 编辑视图默认显示活动工作结果，原始结果在只读对照视图或切换模式查看；橡皮清成 0 是明确的工作状态，不能被底层原始 AI 叠加补回。删除只作用于所选图层/实例；接入新 AI 结果创建独立版本，不覆盖已有工作图层或清空全工程 Undo。采用新版本作为工作结果是明确、可撤销的操作。
- 清空当前切片与清空全部工作标注明确分开，均可撤销；工作区“重置”默认仅重置显示，不再隐式丢弃标注。
- 手工修改不伪造新的模型置信度。类型预测始终绑定生成它的模型结果版本；范围被修改后显示已人工修订，不能冒充已经重新运行分类。
- 自动记录病灶编号、范围、类型预测/未知、来源、操作与保存时间、体素数；真实几何/HU 条件允许时才记录体积与 HU 统计。

## 2. 当前代码核查与影响

下表记录实施前基线 `6619cf5` 的差距及处理方向；已实现范围以第 6 节实施记录为准。

| 现有路径 | 已有能力 / 缺口 | 计划处理 |
|---|---|---|
| `main.py:is_supported_classic_ct / _read_dicom_dir` | 仅 Classic CT；多序列只取切片最多的一组 | 模态入口与检查/序列容器分离，保留各序列身份和独立状态 |
| `main.py:_build_volume_hu / _apply_series_capabilities` | 强度、HU 与几何能力已有防护；当前工作状态围绕一个体积 | 增加模态中立的强度/单位结构，CT HU 能力继续独立证明 |
| `main.py:_render_clinical_plane`、`mpr_geometry.py` | 三视图 mask 显示和轴翻转映射已存在 | 复用已验证路径，统一引入视图到来源体素的编辑映射 |
| `annotation_lab.py:handle_seg_paint / handle_annotation_added` | 像素与普通标注编辑限制在 Axial | 接入三平面编辑事务；普通标注不再仅用轴状层号定位 |
| `graphics_view.py:ROIGraphicsItem._commit` | 直接改写 ROI 字典 | 改为提交 before/after 事务，避免绕开 Undo |
| `annotation_lab.py:_push_mask_undo / _push_volume_undo` | 部分 mask 内存历史；整卷专属槽位会合并历史 | 用可序列化命令取代槽位式快照，保留真实时间顺序 |
| `annotation_lab.py:save_project / _load_saved_mask` | 全切片 JSON + 整卷 NPZ；各文件分别替换，文件名基于患者；未保存历史和完整来源 | 新工程包一次提交，按检查/序列绑定，恢复最终状态及历史 |
| `main.py:load_data` | 旧 mask 恢复受 AI 可用性条件限制 | 人工标注恢复与 AI 推理资格解耦，身份与空间校验不放宽 |
| `main.py:_stop_ai_for_manual_edit / on_auto_ai_finished` | 代次防护已存在，可防止旧 AI 覆盖新编辑 | 保留并扩展到切序列、Undo、配准、后台保存；接入结果不再清空全工程历史 |
| `graphics_view.py:mouseMoveEvent`、`interaction.py:sync_crosshair` | 拖画仍发 hover，冠/矢状方向变化可触发取消交互 | E2 增加编辑期间导航冻结，使用实际 Qt 鼠标事件验收 |
| `compare_lab.py:_read_compare_dir` | 共享主读取入口，临时恢复两个旧属性 | E1 改为返回独立候选数据；加载对比不得提交到主工程 |
| `registration.py` | 二维切片刚性配准 | 不充当 MRI 三维多序列配准；新增独立适配和验证 |

保存时完全擦空的 mask 必须被保存为有效空结果，不能因 `np.any(mask)` 为假跳过写入，导致旧结果复活。新工程按上述来源/空间两层绑定校验，区分原位与患者空间数据；旧缓存缺必要证明时仍拒绝自动恢复。

代码入口：[加载](/Users/sc/01_Projects/GUI/main.py) 的 `load_data`、[编辑与 Undo / 工程保存](/Users/sc/01_Projects/GUI/annotation_lab.py) 的 `_paint_document / _undo_mask_edit / save_project`、[原二维配准](/Users/sc/01_Projects/GUI/registration.py)。规划阶段仅做源码核查与合成风险探针；实施测试另记，历史审计 PASS 不作为新增功能的验证。

## 3. 推荐结构与保存方案

### 新增纯逻辑模块，沿用 Qt 与纯逻辑分离

| 拟新增模块 | 责任与主要接口 |
|---|---|
| `study_data.py` | `StudyDocument / SeriesVolume`：检查、序列、来源帧、强度单位、空间变换、能力判据与版本 |
| `annotation_state.py` | `EditCommand / EditHistory`：三维编辑、普通标注变更、apply/undo、差分编码、恢复校验 |
| `project_store.py` | `save_project_snapshot / load_project_snapshot`：工程包、版本、历史、来源、旧格式只读迁移 |
| `series_registration.py` | `RegistrationResult`：三维序列变换及质量/失败原因，无 Qt 依赖 |

现有 `main.py / annotation_lab.py / graphics_view.py / ui_builder.py / interaction.py` 负责交互和调度，`compare_lab.py` 调整读取适配与能力守卫。避免同时重写重建实验室、随访算法或器官推理算法；MRI 的单位及能力条件须传到这些旧入口，防止 MRI 被送入仅适用于 CT 的路径。

读取函数返回尚未接入的候选检查/序列，不直接改写活动 `StudyDocument`。主加载完成读取、解码、身份校验并处理旧工程保存后，才在 UI 线程一次提交；失败或取消保留旧工程、图层、历史及 dirty 状态。对比加载只持有自己的候选，不能依靠恢复两个旧属性回滚新的全局状态。同 Study 内切换活动序列不重建文档或清历史。所有 AI/配准回调通过 Qt 信号到主线程，按文档 generation、series ID、输入 revision 验证后接入。

`StudyDocument` 包含各 `SeriesVolume`、只读 AI 图层、可编辑图层、普通标注、配准变换和全工程最近 20 步历史。各操作记录 series ID、layer ID、来源网格指纹、before/after 差分、操作编号和描述。局部编辑存差分，整卷变更存压缩分块数据；不序列化 Qt 对象或 pickle 对象。

### 工程包

采用单个 `.miwproj` 文件（标准 ZIP）：`manifest.json` 保存版本、检查/序列身份、普通标注、配准与来源；各序列 NPZ 保存图层和有效置信度；历史数据保存可重放的最近 20 步；`summary.csv` 对应同一文档版本。完整原始 DICOM 不打入工程，重新显示或编辑某个序列仍需要对应影像；缺少影像不等于工程内该序列及其标注已被删除。

以检查为默认保存单位，各序列在包内独立绑定。默认文件标识取 StudyInstanceUID 的 SHA-256；包内验证每个序列的来源绑定，患者空间数据还验证空间指纹，不靠患者姓名或相同形状匹配。缺少必要身份信息时不猜测自动关联。不同检查不共用 Undo 栈；恢复一个工程时一起恢复它的历史。恢复副本的显式路径优先于默认 Study 文件名。

**部分载入的保存契约：** 发现同 Study 的已有工程时，先校验工程结构及包内数据完整性，以已有完整 manifest、图层和历史建立 `StudyDocument`，再把此次目录中的来源影像逐序列匹配接入。只载入一个子目录、源文件被移动或匹配失败时，其他序列保留为“来源未连接”，其标注、变换、统计与历史仍随完整工程保存；缺失或身份未验证的来源不能用于编辑、叠加或重新计算统计。新发现且身份可验证的序列可加入，不能用本次目录清单重建并缩减已有工程。已有工程无法完整读取或校验时停止覆盖原件，禁止把局部新文档自动写到它的路径；只有符合下述恢复副本条件时可另存恢复结果。

未连接序列所涉及的 Undo 不因载入子集而丢弃或重排。若栈顶操作涉及未连接来源，提示重新定位影像，验证通过前不执行该操作，也不跳过它撤销更早操作；新编辑仍按全工程最近 20 步规则正常入栈、淘汰最旧操作。保存后的摘要保留未连接序列的既有统计及来源状态，不伪称本次已重新计算；重新连接后通过原有身份/空间检查才恢复交互。

新输出目录使用 `Annotation_Projects/`，可选目录并通过 QSettings 记忆。工程文件、新输出目录及自动生成数据加入 `.gitignore`。旧 `Exported_Lesions/` 仅做兼容读取，本任务不覆盖其中产物；迁移后的新工程优先，损坏时不静默回退为旧版本。旧缓存缺置信度或来源的字段显示未知，不能用当前权重哈希补写成历史生成证据。

**旧缓存的图层迁移契约：** 通过现有恢复校验的旧 mask 只迁入“历史工作结果（生成/修改来源未知）”，保留其体素标签，不将它复制为原始 AI 图层。旧格式没有保存原始 AI 结果和操作历史，即使没有人工标记值 255，也不能推断未经人工修改；原始 AI 对照显示不可用，迁移前 Undo 不可用，迁移后的实际编辑开始记录新历史。可记录导入文件哈希与导入时间作为迁移证据，但不能当成生成模型的身份。迁移不自动重跑 AI 补造历史；日后明确启动的新推理另记新结果版本。

旧 JSON 的局部标注保留来源切片坐标；`all` 标注保留在来源轴状切片上重复显示的参考标记语义，不补造三维病灶或跨序列空间对应。其显示、删除和 Undo 单独验收；未能转换的对象须明确报告并保留原文件，不能静默丢弃后宣称完整迁移。

保存采用一致的已提交状态快照，临时文件写完、flush/fsync 后一次 `os.replace` 提交；失败保留上一份完整工程。历史与最终 mask 同一次提交，包内 manifest、最终图层、历史分开记录版本、shape/dtype 和内容摘要以独立校验；载入拒绝不支持的 schema、非法引用/尺寸/标签、对象 pickle 和异常解压规模，验证通过前不替换活动文档。

**历史损坏恢复：** 仅当 manifest、全部最终图层及其必需元数据独立验证通过，而损坏局限于历史时，允许用户选择“恢复标注副本”。原件只读，生成带独立 document ID 的 `{study_hash}_recovered_{unique_id}.miwproj`；记录来源工程哈希与丢失历史原因，旧历史不可用，新编辑从恢复点建立历史。后续自动保存始终指向该新路径，重开时通过显式打开副本恢复，不猜测覆盖同 Study 的默认工程。必要最终数据或 manifest 损坏时拒绝普通恢复，不把缺失图层当空图层保存。

后台最多一个运行中的保存任务和一个合并后的最新 revision 请求；待处理请求不堆积整卷副本。文档修改在主线程提交，保存持有不可变块或等价隔离快照，压缩/文件 I/O 在 worker 完成，回执通过 Qt 信号返回。历史采用压缩分块与按需加载；不能每笔深拷贝所有序列及 20 步整卷历史。E3 用代表体积检查峰值内存、保存积压和 UI 响应；资源不足应失败可见并保留已提交状态，不得截断历史冒充成功。

所有被接受的持久化变更统一递增文档 revision、设置 dirty 并调度保存，包含编辑、Undo、导入/迁移、AI 结果版本接入和配准变换；不要求发生手工编辑才保存自动结果。过期/失败回调和未提交预览不修改 revision。最后一次已提交变更后空闲 2 秒自动保存，连续变更每 30 秒安排一次；编辑预览期间也只保存上一个完整提交状态。保存期间的新变更保持 dirty，旧回执不能将它标成已保存。切换检查或关闭时先取消未完成预览、封闭旧文档的新结果接入，再保存最新提交版本；保存失败提供重试、更换位置、取消离开或明确放弃修改。恢复后的人工结果和有效空结果不自动触发 AI 重算。

界面提供保存状态、最后成功时间、完整路径、`.miwproj / JSON / NPZ / CSV` 格式说明和打开目录入口；日常保存不逐笔弹窗。

### MRI 多序列配准

先利用 DICOM 空间信息建立坐标联动，并区分“元数据定位”与“已验证配准”。同一 FrameOfReferenceUID 不能证明完全没有扫描间运动。需要图像配准时优先使用成熟的 SimpleITK 三维刚性方法；首期不加入非刚性形变配准。强度图用适当连续插值，标签图只用离散标签插值；来源数据保持原位，保存变换、方向、参数和质量状态。

SimpleITK 提供三维刚性变换、互信息及多分辨率配准，可作为适配基础；配准分数改善不单独等于解剖对齐成功。以已知变换合成数据、空间标志点和获准 MRI 病例检查误差与失败拒绝行为。[官方配准说明](https://simpleitk.readthedocs.io/en/master/registrationOverview.html)

E0 的本机 `dicom_gui` 元数据核查：SimpleITK 2.5.3、nibabel 5.4.2、torch 2.11.0、onnxruntime 1.23.2 已安装，MONAI 未安装，命令退出 0。当时 SimpleITK 尚未列入应用直接依赖；E4 已按采用方案在 `requirements.txt / environment.yml` 固定已有的 2.5.3，并同步 `pyproject.toml` 下界声明和依赖检查，没有下载安装或升级其他锁定依赖。新模型依赖仍须在隔离环境评估。

## 4. 实施顺序与验收

| 阶段 | 工作与范围 | 通过条件 |
|---|---|---|
| E0 基线与契约 | 记录实施 SHA/工作区，补关键失败用例，冻结来源/空间绑定、加载事务、编辑事务及工程 schema；核查模块守卫、MRI 验证输入和依赖 | 关键合成负例能复现旧限制；MRI 验证来源/格式/获取条件和现有环境缺口明确；未决输入不拖到 E4 才发现 |
| E1 影像与空间基础 | 检查/序列容器、CT/MR 读取、来源绑定与空间能力分离、统一平面采样；改 `main.py / dicom_geometry.py / mpr_geometry.py / compare_lab.py / interaction.py` 及新数据模块 | CT/MRI 分开加载；多序列不混叠；斜向/异方性位置正确；对比读取不污染主工程；无法安全绑定时编辑入口已禁用 |
| E2 编辑与 Undo | 三视图像素/普通标注、笔画期间导航冻结、单体素精修、原始/人工图层、统一 20 步 Undo；改交互与标注模块 | 三个方向交替编辑同一位置一致；实际鼠标拖动不被自身 hover 取消；点击只改一体素；混合操作按顺序还原；原始 AI 不被覆盖 |
| E3 工程保存 | 新工程包、历史落盘、恢复副本、旧格式只读迁移、全部持久化变更触发保存、状态提示与生命周期收尾 | 关闭重开内容/历史一致；部分载入不缩减工程；旧缓存不冒充原始 AI；纯 AI/配准结果也落盘；损坏原件不被覆盖；队列不积压整卷副本，写失败保留旧工程 |
| E4 MRI 联动 | 空间对应、三维刚性配准适配、变换持久化与对应标注显示 | 已知空间变换定位正确；真实病例验证结果有出处；无重叠/错位/失败时不强套标注；切换序列不损坏来源 mask |
| E5 回归与交付 | 旧 CT 阅片、器官 AI 缓存、重建/随访能力入口回归；复核已随各阶段同步的架构说明，完成使用说明 Markdown | 新功能验收逐项有实测记录，原有 CT 核心流程不退化；未验证的 MRI 输入类型和模型能力明确列出 |

**各阶段共用的模块登记门槛：** 每次新增顶层模块，同一阶段同步更新 `pyproject.toml` 的 `py-modules`、`docs/ARCHITECTURE.md` 模块清单及数量说明，并调整 `tests/test_gui.py` 的数量解析与固定 20/11 断言，使检查仍比对真实根模块、依赖声明和架构清单。不得删除一致性守卫；保留并验证“从声明中移除一个实际模块即失败”的 known-bad 检查。完成上述同步后再运行该阶段 `SKIP_REAL_DATA` 回归，不能把这些更新推迟到 E5。现有门槛见 [清单检查](/Users/sc/01_Projects/GUI/tests/test_gui.py:6627)。

E0 先列出必须替换语义的旧回归：仅 CT、非 canonical 一律禁止 MPR、重置清空标注、旧 JSON/NPZ 写入、AI 完成清 Undo。只对已实施的新行为改写断言，并用旧格式只读迁移、旧 CT 推理守卫、无效几何负例替代相应保护，不能批量删除失败用例。引入 SimpleITK 等直接依赖时，同阶段同步 `requirements.txt / environment.yml / pyproject.toml` 及依赖完整性检查；未获采用/安装授权时保留可降级入口，不先导入一个发布环境缺少的包。

E1–E4 是完整工程交付的组成部分，不能完成一个阶段就把全部工程目标标成完成。三维配准或 MRI 实例验证若受额外授权阻碍，先完成独立的编辑/存储工作，并精确报告剩余范围。

### 必测行为

1. 非对称合成体积，在三平面、不同缩放、平移、异方性和有效斜采集上点击已知位置；只修改预期来源体素，边界外点击不修改任何内容。
2. 跨切片/视图/序列混合画笔、橡皮、标尺、ROI 移动、批量删除、整卷清空；逐步 Undo 同时恢复数据、来源和可用置信度。重开后继续执行最近 20 步。
3. 编辑过程中切换工具、平面或序列；未完成操作不写入错误切片，也不被自动保存。
4. 完整保存后重开：各序列、全局/局部普通标注、原始/人工图层、实例 ID、配准变换、历史一致；完全擦空仍保持为空。
5. 同患者不同 Study/Series、相同 shape 不同顺序、错 UID、缺轴约定、错指纹、损坏历史、损坏工程与旧格式逐项验证；拒绝错误关联。
6. 注入序列化失败、磁盘写入失败、最终替换失败、保存期间继续编辑/Undo、切换检查与关闭取消；上一完整工程可恢复，界面不虚报已保存。
7. 旧 AI 结果、旧保存任务、旧配准回调晚到；只能作用于匹配 generation/revision 的对象。
8. MRI 不显示伪 HU，不进入 CT 专用器官模型或 HU 定量/重建路径；CT 的原有能力检查继续有效。
9. 三维配准采用已知变换正例及无重叠、左右错误等负例；记录 target registration error，不以相关性或互信息改善单独判通过。
10. 至少一份获准结构 MRI 多序列真实数据与现有公开 CT 做实际交互验收；合成数据 PASS 不冒充 MRI 真实数据支持验证。
11. 创建含 A/B 两个序列及混合历史的工程，只载入 A 的子目录，分别模拟 B 未提供、文件移动和身份不匹配；编辑 A、保存、重开后，B 的图层、变换和既有统计仍完整，历史仅发生新命令入栈及正常 20 步淘汰。栈顶涉及 B 时不跳步 Undo，重新定位并验证 B 后可按序撤销；已有工程损坏时拒绝用 A 的局部状态覆盖。
12. 用合成旧缓存模拟器官标签被画笔修改、被橡皮清零以及含 255 的情况；通过旧格式身份校验后迁入的工作 mask 与缓存相同，原始 AI 对照及迁移前历史均不可用，新编辑可撤销，迁移过程没有触发推理；缺旧轴约定或指纹的缓存继续拒绝自动恢复。
13. 分别缺 IOP、IPP、PixelSpacing 但来源帧身份完整的输入：只能原位编辑，保存/重开/Undo 一致，无伪毫米数据；像素或 SOP 身份变更拒绝错配，无法建立来源绑定时编辑前禁用。新原位模式不使旧 AI 缓存的负例变为通过。
14. 实际 Qt 鼠标按下→纵横拖动→松开覆盖三平面及斜采集；完整笔画只提交一次，hover 不触发取消。显式换面、滚轮导航和切序列按规则取消预览，保存中途不含半笔。原始/人工对照下擦除后工作结果确实为空，原始版本保留，新 AI 版本接入不清旧历史。
15. 历史块损坏但完整最终状态有效时，恢复副本→编辑→Undo→自动保存→显式重开可完成，原件哈希不变；manifest/最终图层损坏时拒绝普通恢复。注入损坏 shape/dtype、非法引用及不支持 schema，不能覆盖活动工程。
16. 注入有效与过期 AI/配准回调，不做手工编辑：有效结果产生对应 revision 的工程，过期结果不改 dirty 或内容；慢保存期间连续提交只合并最新待保存请求。对比成功、MRI 被旧随访入口拒绝、解码失败及取消均不改变主工程、标注、Undo 与 dirty。

沿用 `tests/test_gui.py` 自包含测试与 `SKIP_REAL_DATA` 二分，不另装测试框架。关键编辑/存储逻辑按 TDD 逐行为推进；简单提示文案不用机械补测试。测试 I/O 用临时目录，AI 回调用合成结果，实际昂贵推理另行授权。

实施时在 `conda activate dicom_gui` 后运行 `SKIP_REAL_DATA=1 python tests/test_gui.py`、`ruff check .` 与 `git diff --check`；需要真实数据的验收单列。全套测试必须先确认不会触碰保护产物或擅自重跑昂贵推理，再按项目规则执行。记录实际命令、退出码、基线 SHA 和测试范围，不预填数量或 PASS。

## 5. 肿瘤研究：候选预审与推荐路径

以下核查截至 2026-09-07，深度不等，均未在本机执行模型。分支名、论文和模型卡只代表此次读取的来源；正式试跑前须固定代码提交、权重文件哈希和输入协议。

| 候选 | 已核实的能力 / 证据 | 当前判断 |
|---|---|---|
| BiomedParse v2 | 官方支持 3D CT/MRI、多目标及存在性输出；示例仍传入目标文本；有权重链接和 CPU 选择入口。[说明](https://github.com/microsoft/BiomedParse/tree/v2)、[推理](https://github.com/microsoft/BiomedParse/blob/v2/inference.py) | 优先核查通用分割组件，不能把文本目标名直接当成自主识别的瘤种 |
| CLIP-Driven Universal Model | 固定输出含肾、肝、肺等部位肿瘤；脚本直接调用 `.cuda()`，存在权重下载入口。[说明](https://github.com/ljwztc/CLIP-Driven-Universal-Model)、[脚本](https://github.com/ljwztc/CLIP-Driven-Universal-Model/blob/main/pred_pseudo.py) | CT 分割备选；CPU 需适配，部位标签不等于病理类型 |
| Raidionics | 已有 MRI 肿瘤分割与报告工作流；官方 FAQ 测试明确选择 meningioma 任务。[项目](https://raidionics.github.io/)、[FAQ](https://github.com/raidionics/Raidionics/wiki/Frequently-Asked-Questions-(FAQ)) | MRI 专用组件/流程参考；本次证据未证明未知瘤种自动分类 |
| MONAI BraTS MRI | 四组对齐 MRI 输入；输出 ET / TC / WT 子区域。[模型说明](https://huggingface.co/MONAI/brats_mri_segmentation/blob/main/docs/README.md) | 专用分割备选，不能用“模型针对 Glioma”替代类型识别 |
| TotalSegmentator 专用任务 | 提供 `lung_nodules`、`liver_tumor` 等任务。[官方任务说明](https://github.com/wasserth/TotalSegmentator#subtasks) | 器官/病灶分割组件；未形成自动瘤种识别证据 |
| LesionLocator | 使用点或 3D 框提示进行病灶分割与追踪。[官方接口](https://github.com/MIC-DKFZ/LesionLocator) | 只有接上自动检测且验证组合后，才可能符合免人工定位要求 |
| MultiTalent | 多数据集分割训练框架，入口包括自行准备数据和训练。[官方仓库](https://github.com/MIC-DKFZ/MultiTalent) | 暂不作为无需训练即可接入的完整方案 |
| Triad | 当前仓库 Quick Start 加载 encoder/backbone 权重。[官方仓库](https://github.com/wangshansong1/Triad) | 未确认有本任务可直接运行的分类+分割成品；暂低优先级 |
| EfficientNetB1 + U-Net 研究 | 论文提出 Glioma / Meningioma / Pituitary adenoma / No tumor 分类及分割。[论文 v2](https://arxiv.org/abs/2304.10039v2) | 分类组合线索；可用权重、患者级证据和完整 3D 输入链尚未核实 |
| PANORAMA baseline（R1 新线索 10） | 官方两级 nnU-Net：静脉增强 CT 自动定位胰腺、生成 PDAC detection map 与患者级 likelihood；列出 Zenodo 权重入口。[仓库](https://github.com/DIAGNijmegen/PANORAMA_baseline)、[实际输出代码](https://raw.githubusercontent.com/DIAGNijmegen/PANORAMA_baseline/main/src/process.py) | 输出检测区域，不是多瘤种分类；不能直接把其 map 当精确肿瘤边界。权重版本/许可、CPU 和边界证据待核实 |
| PanDx（R1 新线索 11） | 官方代码给出 PDAC detection map/患者 likelihood、模型链接；输入 CECT，README 环境要求 CUDA，并有可调病灶扩张参数。[官方说明](https://raw.githubusercontent.com/han-liu/PanDx/main/README.md) | 备选专用检测组件；未证明可接受的 CPU 路径、精确分割和其他类型拒绝，暂未选定 |
| BRISC 2025 与基线模型（R1 新线索 12） | 作者论文 v5 提供 T1-CE 二维图像的 Glioma / Meningioma / Pituitary / Non-tumorous 标签与专家复核 mask；明确不能保证患者级划分独立。[论文 v5](https://arxiv.org/html/2506.14318v5) | 可作二维方法/参考数据线索，不能作为完整 DICOM 病例链或独立患者测试的证据；未取得可固定的基线权重 |

### 影响选型的新增发现

BiomedParse 的模型源码按输入 prompt 生成 mask 与对应存在性输出。可以研究由软件使用固定候选类别表发起查询，但这是待验证的组合设计；多个类别输出的分数可比性、未知类别拒绝、同一病灶类型区分都需单独验证。CPU 入口只证明代码有选择分支，依赖、内部算子、峰值内存和整例速度仍未知。[模型源码](https://github.com/microsoft/BiomedParse/blob/v2/src/model/biomedparse_3D.py)

2026-09-07 进一步读取官方 v2 分支：依赖文件固定 `torch==2.6.0+cu124`、`numpy==1.26.4`，并包括 DeepSpeed；发布依赖不能直接套进本项目 CPU 环境。代码 LICENSE 已确认为 Apache-2.0，但权重具体版本、字节摘要及其单独许可仍未完成核实。结论是需要隔离的 CPU 依赖验证，不是断言 CPU 永远不可运行；本轮未安装或下载。[依赖原文](https://raw.githubusercontent.com/microsoft/BiomedParse/v2/assets/requirements/requirements.txt)、[代码许可](https://raw.githubusercontent.com/microsoft/BiomedParse/v2/LICENSE)

PanDx 的实际 `main.py` 用 `--inv_alpha` 控制病灶区域扩张，输出 `pdac-detection-map/*.nii.gz` 和 `pdac-likelihood.json`；代码将裁剪区域放回原始体积，并复制原图空间信息。因此它可作为专用检测组件线索，但文件格式和空间元数据保留本身不能证明边界精度、类型区分或本机可用性。当前读到的是 main 分支代码，尚未固定代码 SHA 和权重产物。[实际输出代码](https://github.com/han-liu/PanDx/blob/main/main.py)

CLIP-Driven 仓库 LICENSE 为 CC BY-NC-ND 4.0，文本限制非商业使用及分发改编材料。不能默认复制修改后随本项目发布，也不能认为独立进程自动消除许可义务；具体代码/权重的接入与分发授权未澄清前只列研究备选。[仓库许可证](https://github.com/ljwztc/CLIP-Driven-Universal-Model/blob/main/LICENSE)

推荐顺序：优先核查 BiomedParse 的通用定位/分割能力及自动候选查询能否形成可信分类；同时仅针对缺失的类型识别环节寻找可用分类器。MRI 专用分割组件作为组合备选。CLIP-Driven 因 CPU 适配与许可条件降低产品接入优先级。以上是预审排序，不是已经选定部署模型。

### 固定筛选与停止方法

- 三条路线：统一模型；自动检测+分割+分类；由模态/解剖部位自动选择专用模型组合。可使用影像元数据辅助路由，不从测试文件名、患者文件夹或答案标签获得瘤种。
- 正式候选池最多 12 项，本轮已达 12 项，包含原预审 9 项，不另外增加 12 项。完整组合深入核查最多 3 条。仅论文、仅演示图、无权重、必须人工指定病灶/瘤种、只给部位标签的方案不能直接列为完整可接入。
- 证据卡至少包含：代码/权重来源及版本、许可、输入模态/序列/预处理、输出标签准确含义、人工提示依赖、完整病例处理能力、分类与病灶对应方式、训练/测试来源、患者级划分、阴性/OOD 情况、CPU 路径、未解决问题及下一动作。
- 排序依次考虑完整任务匹配、成品代码/权重、独立验证证据、CPU 可行性、接入成本。不要用排行榜高 Dice 抵消缺失分类或需预知瘤种的问题。
- 找到证据完整且可试跑的优先组合后停止扩大搜索，转入验证准备。达到候选/深查上限，或三条路线已覆盖且补充检索无新增合格候选，结束这一轮检索。
- 缺权重、许可不可接受、CPU 关键算子无可行替代且不获 GPU 授权、需要本轮排除的训练，均作为停止该候选的依据；发现补救方法时先给具体成本，不无期限追查。
- 研究允许以“当前约束下没有完整合格方案”结束，但必须列出已解决环节、缺失证据和重新启动的条件；不得表述为技术上永远做不到。

### R1 有界研究结案（2026-09-07）

**结论：本轮没有筛出在现有 CPU、无需新增训练的约束下，证据完整且可直接试跑的“自动发现 + 精确范围 + 病灶对应瘤种”组合。** 已确认分割组件、部分检测组件和类型分类研究线索存在；缺少的主要是可固定的分类产物、它与完整病例内各病灶的绑定及阴性/未知类型验证。此结论只覆盖下列 12 项和三条组合路线，不证明其他方法不存在或技术上不可实现。R1 以明确缺口交付，R2–R4 未启动。

#### 优先候选证据卡

以下“未核实”都是本轮未通过的证据门，不能在接入时按默认通过处理。所有候选均未在本机运行；论文指标不迁移为本项目指标。

| 候选 | 版本、产物和许可 | 输入、输出与提示依赖 | 验证与 CPU；本轮处置 |
|---|---|---|---|
| BiomedParse v2 | 代码固定 `e02096c03af0d79c6994ffc2d60a49eeb0361e1f`；README 指向 HF 的 `biomedparse_v2.ckpt`，权重快照、SHA-256 和独立许可未核实；代码 Apache-2.0 | 3D CT/MR → NPZ、强度 0–255；CT 按部位窗口，MR 按 0.5/99.5 percentile 裁剪；输入目标文本，输出对应 mask / existence。整卷推理入口存在，输出类别来自 query，未证明无需指定瘤种的病灶分类 | 权重说明对应 CVPR 2025 text-guided challenge 数据；未取得患者级外部多瘤种、阴性/OOD 联合验证。README 有 CPU 分支，依赖仍含 CUDA 版 torch/DeepSpeed。保留为首选分割组件，停止直接集成，重启需权重/许可固定及分类拒绝方案。[固定版本说明](https://github.com/microsoft/BiomedParse/blob/e02096c03af0d79c6994ffc2d60a49eeb0361e1f/README.md) |
| MONAI BraTS MRI | HF `MONAI/brats_mri_segmentation` 的本轮 main 配置；加载 `models/model.pt`，尚未固定完整 bundle 快照、权重哈希及权重许可 | 4 个对齐 MRI 通道 T1c/T1/T2/FLAIR、1 mm³；按通道非零强度标准化。输出 TC/WT/ET，保存标签 1/2/4 的 NIfTI；无需点/框，但没有跨瘤种分类头，不能把“针对 Glioma 训练”当检测到 Glioma | 模型说明为 BraTS 2018 内部分割；患者清单与本项目外部隔离、无瘤/OOD 未核实。配置有 CPU fallback，但 AMP 和大滑窗仍需实际兼容性/资源验证。停止作为完整组合，保留专用分割备选。[模型说明](https://huggingface.co/MONAI/brats_mri_segmentation/raw/main/docs/README.md)、[实际推理配置](https://huggingface.co/MONAI/brats_mri_segmentation/raw/main/configs/inference.json) |
| Raidionics | GUI `fcb5d92f9ab8150336cd4ba23968823cc49f4aa2`；其 RADS submodule `892ec56a015b8d665eef26601fbd25ef34e93c40`。GUI/RADS/model 仓库均有 BSD-2-Clause；模型 release 1.2.0 的具体条目见下方 | MRI 3D 分割/报告；FAQ 示例用 T1-CE + FLAIR，须正确标序列并选择 Meningioma。多个瘤种的专用分割器存在；未证明软件自动从未知瘤种选择正确任务，也未证明各模型分数可跨瘤种比较 | 有 macOS/ARM 软件发行，模型为 ONNX，均不等于本机 CPU 实测通过；训练/测试患者身份、阴性/OOD 和对各病灶分配类型的证据未核实。停止直接组合，保留工程/专用分割参考。[GUI 固定版本](https://github.com/raidionics/Raidionics/tree/fcb5d92f9ab8150336cd4ba23968823cc49f4aa2)、[FAQ](https://github.com/raidionics/Raidionics/wiki/Frequently-Asked-Questions-(FAQ)) |
| EfficientNetB1 + U-Net | 论文 `2304.10039v2`；本轮论文及按论文号/权重的补充检索未取得可确认的作者 checkpoint/推理包，代码及权重许可未核实 | MRI 二维图像分类 Glioma/Meningioma/Pituitary adenoma/No tumor，另一个网络做 segmentation；未证明连续 3D 体积预处理、原坐标回映射及多病灶对应。分类标签语义接近需求，完整输入协议仍缺 | 图像划分不能替代患者划分；不同数据上两个网络各自的指标不能相加成联合结果。No tumor 类不等于 OOD 拒绝。CPU/完整病例均无本机证据；因缺成品权重停止，不擅自转训练。[论文 v2](https://arxiv.org/abs/2304.10039v2) |
| BRISC + 论文基线 | 论文 `2506.14318v5`（2026-01-28）；作者指向 Kaggle 的数据/代码，当前页面未返回可核实的权重清单，产物版本/许可未确认；论文 CC BY-4.0 不替代数据/权重许可 | T1-CE 的 JPEG 与 PNG mask，四类含 Non-tumorous；不是完整患者 DICOM。专家复核标签/mask，基线分类与分割不自动证明病灶级绑定；尚无可固定的病例级推理包 | 论文明确来源缺患者/序列信息，无法保证独立患者划分；阴性含部分非肿瘤占位，但未构成未知瘤种测试。CPU 未验证。停止成品接入，仅保留二维方法与数据线索；不依据旧版本题名宣称有可用 Swin-HAFNet 成品。[作者最新版](https://arxiv.org/html/2506.14318v5)、[作者数据入口](https://www.kaggle.com/datasets/briscdataset/brisc2025/) |

Raidionics 的产物身份进一步核查：GitHub release ID `92235448` / tag `1.2.0`，公开 API 列出 `Raidionics-MRI_Meningioma-ONNX-v12.zip`（asset ID `95775129`，68,913,186 bytes）与所需预处理组件线索 `Raidionics-MRI_Brain-ONNX-v12.zip`（asset ID `95476319`，69,134,888 bytes）。两者 API `digest=null`，因此这里只确认发布条目，不伪造字节哈希；没有下载或解压，也尚未检查各压缩包内 pipeline 依赖闭包/许可附加项。模型仓库 [tag 许可](https://github.com/raidionics/Raidionics-models/blob/1.2.0/LICENSE) 为 BSD-2-Clause。[发布 API](https://api.github.com/repos/raidionics/Raidionics-models/releases/tags/1.2.0) 及 [发布说明](https://github.com/raidionics/Raidionics-models/releases/tag/1.2.0) 同时表明 MRI Sequence Classifier 尚未发表验证；它识别序列角色，不能被当作瘤种分类器。

#### 其余候选的停止卡

这七项沿用上表的官方代码/论文入口。本轮在任务匹配或产物门已停止，均未固定运行快照/权重哈希；除已明确的 CLIP 许可外，其他代码与具体权重的许可组合未完成核实。未确认的预处理参数、训练/测试患者清单、阴性/OOD 和 CPU 性能均保持“未核实”，不因停止筛选而填写推测值。

| 候选 | 输入、结果与人工依赖 | 完整病例/类型对应缺口与下一动作 |
|---|---|---|
| CLIP-Driven | CT，固定语义标签含部位肿瘤，存在推理/权重入口；脚本直接 `.cuda()` | 语义 mask 不给出所需病理类型；CC BY-NC-ND-4.0 和 CPU 适配未解决。只有许可与可用类型模块均明确后才重启 |
| TotalSegmentator 专用任务 | CT 的 `lung_nodules` / `liver_tumor` 等；选择 task 后分割，具体增强相位/预处理依 task 再核对 | 器官/结节/部位肿瘤不是统一瘤种预测；需逐 task 权重与许可，自动路由及未知类别拒绝仍缺。保留定位/分割组件 |
| LesionLocator | 3D 病灶分割/追踪，需点或 3D box | 未确认可直接接上的自动检测、类型输出与匹配验证；不能把用户手点定位作为免提示实现。找到合格检测/分类产物后再考虑 |
| MultiTalent | 多数据集分割训练框架，需准备数据/训练 | 未取得符合本任务的已训练完整分类+分割包；新增训练在本轮外，停止 |
| Triad | 3D 医学影像预训练 encoder/backbone 权重 | backbone 不等于有分类/分割输出的成品；下游 heads、训练与病例级接口未补齐，停止 |
| PANORAMA baseline | 静脉增强 CT，两级 nnU-Net，自动胰腺定位后 PDAC detection map + 患者级 likelihood；有 Zenodo 权重入口 | 检测 map 不自动满足精确边界，患者概率不等于逐病灶瘤种；缺多类型/阴性/OOD 联合与 CPU 证据。停止完整接入，保留专用检测组件 |
| PanDx | CECT，输出 PDAC detection map/患者 likelihood；含 `inv_alpha` 区域扩张；README CUDA | 空间回填可核查，但扩张区域与精确 mask 的差异未验证，患者概率与实例分类未打通。停止完整接入，重启条件同 PANORAMA |

#### 三条组合路线的推荐与缺口

| 路线 | 推荐设计（尚未实现） | 为什么本轮不能进入完整接入 |
|---|---|---|
| A：统一模型 | 优先保留 BiomedParse v2。软件从模态/解剖区域生成固定候选 query，归并重叠病灶，再判别类型/未知；不要求用户先说瘤种 | 目前只有条件分割/existence 证据；跨 query 分数校准、同一病灶类别冲突与错误 prompt 的拒绝未验证；权重/CPU 也未固定。不能用 query 名填类型作为完成 |
| B：检测 + 分割 + 分类 | 无人工 ROI 的检测器输出病灶实例；分割后将同一实例的合适影像送独立分类器。EfficientNetB1/BRISC 是分类语义与数据线索 | 没有已核实的分类 checkpoint + 连续 3D 输入/输出契约 + 与 detector/segmenter 同域的组合。二维 JPEG 模型不能直接接收任意 CT/MR；增加训练需另行决定 |
| C：自动路由专用模型 | 先确认 CT/MR、部位、增强/序列角色，再选择 Raidionics / MONAI / 专用 CT 组件，未支持输入拒绝并解释 | 路由到器官/序列不能回答病理类型。让用户先选 Glioma 或 Meningioma 会改变需求；未验证的序列分类器不能消除输入角色问题。缺自动瘤种选择、联合验证和资源证据 |

排序仍为 A 优先研究、B 补缺、C 备选；这是后续证据方向，不是部署承诺。可复用的工程接口已经独立完成：原始 AI 版本只读、来源网格绑定、人工修订与 Undo、工程包及记录。任何新模型仍须满足 R4 门槛才进入这些接口。

#### 候选验证输入与参考证据

| 数据线索 | 能回答的问题 | 本轮不能据此声称的内容 |
|---|---|---|
| BraTS 2018 官方发布 | T1 / T1Gd / T2 / FLAIR，配准、去颅骨、1 mm³ NIfTI，专家人工修订 ET/ED/NCR-NET；可匹配 MONAI 的分割语义 | 与候选训练重叠必须按患者清单排除；challenge 隐藏验证/test 标签不假定可离线获取。Glioma 内分区不能证明跨瘤种分类或阴性拒绝。[官方输入与标签](https://www.med.upenn.edu/sbia/brats2018/data.html) |
| UCSF-PDGM | 官方集合说明为病理证实 diffuse glioma 的术前 MRI，作为有类型依据的潜在外部来源 | 当前集合详情抓取超时，未核实本次具体患者、所需四序列/参考 mask、许可与下载范围；不把集合规模当可用病例数。不覆盖 Meningioma/Pituitary/阴性。[官方集合](https://www.cancerimagingarchive.net/collection/ucsf-pdgm/) |
| BRISC v5 | 同图的二维 mask 与类别；可检查分类/分割输出语义和像素回映射 | 不是患者级独立整例验收，不能恢复真实 LPS 或充当 Classic MR 多序列工程数据。类型来自专家复核影像标签，不冒充每例都有病理报告 |
| 当前 RIDER CT / PROSTATE-DIAGNOSIS MRI 线索 | 前者用于已完成的 CT 工程链，后者拟用于 E4 多序列空间/交互 | 都不能替代当前缺失的多瘤种联合测试集；PROSTATE-DIAGNOSIS 尚未获得确切 Classic MR 同 Study 输入，不算通过 E4 |

输入角色识别建议：CT/MR 先依据已验证 DICOM 元数据；MRI T1/T1c/T2/FLAIR 结合 SeriesDescription/ProtocolName、采集参数和 ContrastBolus 信息，或经过验证的数据集 manifest。它们均只提供角色证据，不能从路径里的瘤种字符串获得答案。元数据冲突/缺失时停止该模型；同名序列不默认同角色，多序列必须同患者/检查并通过空间验证。四通道模型按其固定配置的真实顺序送入，不能缺一组就复制另一组。CT 未证实 HU/增强相位时不套对应 CT 模型；NIfTI 转换保留来源 affine 与往返坐标记录。这些属于 R2 适配协议建议，未实施为自动模型入口。

**停止依据与重启条件：** 原 9 项加 PANORAMA、PanDx、BRISC 共 12 项，三条路线已逐一分析；补充检索使用论文号 `2304.10039` 与“brain tumor classification segmentation pretrained weights 3D automatic glioma meningioma”，随后只核查作者材料，不把搜索摘要当验收。达到候选上限后结束扩展。本轮不申请把单独分割器直接集成成肿瘤识别功能。重启至少需：可固定的分类/联合模型产物及可接受许可、符合其输入协议且具备 mask/类型依据的病例清单、阴性和不支持瘤种的拒绝方案、获准的隔离 CPU 冒烟范围。确切输入/权重仍缺时不装环境、不下载整套数据。R3 数量、阈值与划分只有在选定范围和参考数据后预注册，现阶段不编造数值门槛。

### 下一阶段验证包（R2–R4 尚未启动）

R1 只读核查要求及本轮结果：已交付上方证据卡、三个组合判断和候选数据清单。没有得到证据完整的可用分类/联合产物；具体权重、依赖和许可尚未确认的项逐项作为未通过门记录，未伪称已经具备试跑条件。不为只有分割功能的模型申请整套肿瘤识别集成。

R1 的输出还须列出拟验证的具体模态/序列组合、瘤种标签粒度、预处理及输入角色识别方法，和匹配的参考 mask/类型证据；“支持 MRI”不能替代 T1/T1c/T2/FLAIR 等实际输入条件。缺序列、无法确认输入角色或无匹配参考数据时注明不能进入哪一步。选出组合后、查看测试结果前形成验收协议，明确样本最低要求、调试/验证/测试划分、检测/分割/分类各项通过阈值与依据；阈值及参考数据未定时 R3/R4 不具备启动/通过条件。当前计划不编造跨瘤种通用精度门槛，也不保证 R1 一定找到合格组合。
R2 获准后做隔离 CPU 冒烟：固定实际代码 SHA、权重 SHA-256、环境锁文件和一例获准输入；从最小 batch 开始，记录形状、坐标回映射、运行失败原因、wall time 与 peak RSS。建议单次作业默认 15 分钟上限、RSS 预算不超过物理内存一半且最高 8 GiB；BiomedParse v2 后续提出的 12 GiB 特定修订见“R2 试跑准备”，须单独获准，未批准不替代原建议。这些是拟定停止预算，不是性能实测或产品速度承诺。超限即中止该配置并报告，不能悄悄转 GPU/云端。能加载权重不等于通过整例冒烟。

每次运行在新的 `Annotation_Projects/research_runs/{run_id}/run.json` 保存机器可读证据，不写入既有 `experiments/results/`。至少包含 schema/run ID、代码 SHA 与未提交改动状态、权重及环境锁文件 SHA-256、CPU 型号/架构/核心数、OS、物理内存、设备、线程数、batch 与预处理配置、输入文件哈希/形状/几何、精确命令、开始/结束时间、wall time、peak RSS 及单位、测量工具/版本与主进程或进程树口径、输出文件哈希、退出码和失败/超限原因。由运行包装器记录开始并收尾，失败或主动超限也写记录；未完成或测量缺失必须显式标记，不能填 0 冒充实测。R2 通过条件包含 JSON 存在、可解析、必需字段齐全且对应本次输入和产物；缺证据时记为未完成验证，不报告性能通过。后续 R3 的新性能运行沿用此约定。

成功运行的性能记录优先复用现有 `experiments/performance_artifact.py` 构建/校验逻辑；新的 run 元数据和失败状态使用明确版本的外层记录补充，不把缺测或失败塞成旧成功 schema 的伪数值。不重写既有 performance artifact 或改变历史实验设计。

R3 可行性验证：试跑前固定患者列表、参考 mask、类型标签来源、阴性及不支持类型病例、分割阈值/分类拒绝规则、检测匹配方法、数据泄漏排查和指标计算方法。优先用与训练数据分离的公开病例；现有 RIDER 单序列不能代替多瘤种分类验证。未取得参考 mask 与类型依据的数据不能伪充有标注测试集。

报告检测 sensitivity / precision 和每例 false positives、病灶级 Dice / HD95、分类 macro-F1 与混淆矩阵、拒绝比例，以及同一病灶“定位、分割、类型同时正确”的联合结果。额外做错误类别 prompt 和无病灶病例试验，排查输出仅跟随提示词的情况。阈值在调试/验证集确定并冻结后再评估独立测试病例；没有足够样本只能报告技术可行性，不能声明临床可靠性。

R4 接入条件：完整病例不需人工指定瘤种，类型预测绑定病灶实例；空间映射可验证；未知/失败/不支持与未检出区分；指标与资源占用达到试跑前明确的产品研究门槛；依赖和许可可接受。不能仅凭单例“看起来对”接入并标成已验证支持。

未来接口建议 `TumorResult`：来源序列/网格、实例 mask 与 lesion ID、部位、类型预测与未知状态、分割和分类各自来源/版本、可核验分数、坐标变换、运行记录。器官标签、现有人工标记值 255 或文本 query 不作为 tumor type 的事实来源。模型输出进入只读 AI 图层，人工编辑通过工程统一事务完成。

## 6. 本轮状态、权限与下一步

前期规划完成：基线代码核查、需求/边界、实施顺序/验收/接口、原 9 项候选预审及两轮审计。规划阶段没有进行新增功能验收。后续实现、合成回归及 2026-09-08 真实 MRI 验收见下方日期记录；未运行新肿瘤模型，未改写既有研究产物。

第二轮合成探针（基线仍为本文首部 SHA）：在 `dicom_gui` 中以 `PYTHONDONTWRITEBYTECODE=1 python -B -` 执行内存夹具，退出码 0。完整两帧来源可生成现有 fingerprint；分别删除 IOP、IPP、PixelSpacing 后均返回空串。调用现有 `InteractionMixin.sync_crosshair`，体积 `(5,6,7)`、初始光标 `(0,0,0)`、MPR 开启、模拟绘制中，传入 `(2,2)`：Axial 仅重绘，Coronal/Sagittal 均调用取消并重绘。该探针使用替身控件、未创建主窗口；只证明现有函数触发行为，未来必须由上列实际鼠标事件验收补齐。

本文档及当前实现均未提交，具体变更以工作区为准。模块清单及架构随相关阶段同步，使用说明在 E5 完成；冻结的 PDF、签章、原始数据、旧导出和实验结果保持原有保护规则。

当前授权已由用户 Goal 扩展为按本文实施 E0–E5 与研究 R1。新增训练、下载/更换验证数据、安装新依赖、昂贵推理、GPU/云端或对外发布按项目要求单独取得具体授权。代码里能查清的接口、测试和常规设计问题由执行者解决，不重新进行需求访谈。

当前 E0–E3 的编辑/保存行为门与 E3 代表体积检查已通过；E4 已接入三维配准、复核、联动显示、采用 Undo 和自动保存，合成产品回归通过，真实 MRI 输入缺口已由 2026-09-08 两个公开单例验收补齐。最终逐项核对另补了跨序列病灶 ID 关联，并修复延迟适配取消新笔画的问题。E5 已同步中英文使用说明，通过真实 CT 标注闭环及本地全套 1467/1467、数据无关层 1342/1342（均退出 0）；本轮产品代码未改，既有源码/日志哈希均重新一致性核对。R1 达到 12 项候选上限，以证据卡、三条路线及明确缺口结案；没有选出可直接试跑的完整肿瘤组合。本计划 E0–E5/R1 验收完成，不扩张为全部 MRI 格式支持、临床有效性或肿瘤推理功能已实现。

### 实施记录（当前工作区，未提交）

- E0，2026-09-07：启动基线 `6619cf5edec75ea1c831f243a9b438ba81064a3d`，原工作区仅本文未跟踪。`conda activate dicom_gui; SKIP_REAL_DATA=1 python tests/test_gui.py`（日志 `/tmp/gui-e0-baseline.log`）退出 1，`CHECKS total=1084 passed=1083 failed=1`；唯一失败为本文 5 处强调闭合紧接中文，已添加分隔空格。随后通过 `runpy.run_path('tests/test_gui.py')['test_markdown_emphasis_renders']()` 定向重跑该门：23 项通过、0 失败、退出 0。未把定向修复结果写成一次完整全套 PASS。
- E0 来源清查：只读 `*.dcm` 头信息，仓库两个目录 `肺癌/` 与 `RIDER_HU_declared/` 各 233 张 CT，未找到 MRI。候选真实多序列输入为 [TCIA PROSTATE-DIAGNOSIS](https://www.cancerimagingarchive.net/collection/prostate-diagnosis/) 的同次 T1/T2 静态 DICOM（官方索引列 CC BY 3.0）；仅用于工程空间/交互验证，不充当多瘤种分类证据。需先选出确切同 Study 序列、确认 Classic MR/非动态输入及下载体积，再申请单例下载。RIDER NEURO MRI 当前受控访问，不作为默认下载方案；PROSTATE-3T 单 T2 序列不满足本次多序列验收。尚未下载任何数据。MRI 真实验证为明确的后续外部输入条件，不阻碍 E1–E3 合成行为实现。
- E0 环境：仅查已安装元数据，SimpleITK 2.5.3、nibabel 5.4.2、PySide6 6.11.0、pydicom 3.0.2、scipy 1.15.3，退出 0；未装依赖。E1–E3 使用现有产品依赖；E4 的 SimpleITK 正式依赖声明及可用性一起处理。
- E0 契约冻结：工程 schema 1；来源采用 `dicom-source-v1`（原始解码像素、Study/Series/SOP 顺序、shape/网格）；患者空间使用独立可选 geometry binding。加载先生成独立 `SeriesVolume` 候选，完成后由 `StudyDocument` 接入；统一命令包含目标序列/图层/来源、before/after 与操作 ID；保存只收已提交 revision，工程包最终状态与历史分别校验。模块守卫、旧语义替换清单及阶段验收沿用第 4 节。E0 准许进入 E1，尚无新增功能验收通过。
- E1，2026-09-07：实现 `study_data.py` 的 CT/MR 解码候选、来源绑定/独立 affine、`StudyDocument`/序列记录；主界面新增同检查序列选择，切换保留各序列 mask/标注/位置，读取失败和同检查来源冲突保留原文档。对比读取使用独立候选；旧单序列接口转为同一读取器的薄适配。来源身份不全在 UI 编辑入口拒绝。`mpr_geometry.PatientPlane` 用 LPS 重采样非 canonical 来源，标签 nearest-neighbor，点击拒绝边界外坐标；显示、hover、探针及滚轮按对应患者面映射。CT 模型资格及未适配的斜采集 mesh/投影/随访限制保留。
- E1 TDD：来源绑定、读取候选、平面采样、多序列产品入口、斜采集入口、无来源禁编辑、非轴状滚轮均先在缺功能时退出 1，再实现后定向通过。另实测斜采集屏幕探针三个视图读错来源值（3 个 FAIL），已接统一映射并通过。原回归中“有效非 canonical 一律禁止 MPR”断言改为患者空间显示及 CT AI 仍拒绝；来源冲突改验当前工程不被替换，另用独立窗口保留旧缓存错配拒绝测试，未删旧四项守卫。
- E1 回归：基于同一 HEAD 的未提交工作区，`conda activate dicom_gui; SKIP_REAL_DATA=1 python tests/test_gui.py > /tmp/gui-e1-final.log 2>&1` 退出 0，`CHECKS total=1141 passed=1141 failed=0`。包括合成 Qt 操作、24 种有向轴、3 组非方阵链路及新来源/多序列/斜采集测试；不等于真实 MRI 或本地真实数据全套。`ruff check .` 与 `git diff --check` 退出 0。顶层模块/架构/声明一致性检查已同步为 21 / 12，并保留 known-bad 缺模块失败检查。
- E2 首轮，2026-09-07：新增无 Qt 的 `annotation_state.py`，`StudyDocument` 接入统一 20 步历史、压缩分块体素差分及普通标注 before/after 事务。纯逻辑验证跨序列混合操作、标签/置信度/来源同步回退、未连接来源不跳步 Undo、22 次整卷操作只保留真实最近 20 步；AI 原始层自有只读数组，新版本不覆盖工作层，显式采用可撤销。此轮先验证文档 API，后续产品接入见下文。
- E2 产品接入：新文档的三个方向像素编辑与 Undo 使用统一事务；半径控件的 `1 voxel` 模式只编辑一个来源体素。Qt 场景坐标先减 `.5` 接入来源中心映射，稀疏鼠标点补成完整笔画，边界外拒绝命中。按下冻结序列/图层/平面/位置，停止 Cine；hover 仅更新提示，滚轮/工具/平面切换取消预览。现有 Axial 普通标注添加/删除和“当前工作层全卷 mask + 本序列普通标注清空”也接入统一历史。尚未完成下列普通标注跨面和 ROI 交互，不能声称 E2 全部通过。
- E2 TDD/回归：三面真实 Qt 单击和 Coronal 纵横拖动在旧路径复现 5 个行为 FAIL 后修复，8 项实际交互检查通过；纯逻辑历史/AI 工作层检查 12 项通过。首轮扩展回归暴露旧清空未接新 Undo、旧轻量测试对象缺文档属性及新警告缺中英标题，已修复。第二轮 `conda activate dicom_gui; SKIP_REAL_DATA=1 python tests/test_gui.py > /tmp/gui-e2-core-regression-2.log 2>&1` 退出 0，`CHECKS total=1161 passed=1161 failed=0`。`ruff check .` 退出 0；模块/架构同步为 22 / 13，既有 known-bad 模块门继续通过。均为同一 HEAD 的未提交工作区和合成数据，不等于真实 MRI 验收。
- E2 后续实现：普通标尺/路径/ROI 保存创建平面及 LPS 坐标，其他平面显示对应交线/位置；无空间证明时只存来源切片坐标。ROI 移动、缩放和多选 Delete 均为一次事务。当前面清空与整卷清空分开，显示重置保留工作结果和历史。新增独立病灶实例及图层选择、原始 AI 只读对照、采用版本操作；产品 AI 回调创建版本而不覆盖人工层或清历史，合成回调验证未运行模型。真实载入路径已去除 `legacy_undo`；无文档轻量旧接口仅保留兼容测试。
- E2 新失败复现与修复：精修后缩放被复位、窗口 resize 后旧笔画仍可提交、ROI 右下角可见手柄不接收点击均由实际 Qt 鼠标检查复现后修复。22 项非斜/30° 斜采集、三平面、各向异性、缩放后单体素点击、边界拒绝与 resize 取消检查通过；普通标注 11 项实际创建/移动/手柄缩放/批量删除及 Undo 检查进入回归。旧测试中“非轴向禁普通标注”“raw/MR 不许 ROI”“重置删标注”改验当前授权语义，HU/毫米守卫及旧缓存四项守卫保留。手柄定向验证初次通过后命令因 runner 变量拼写错误退出 1，因此仅以下完整回归记为通过证据。
- E2 阶段门：`conda activate dicom_gui; SKIP_REAL_DATA=1 python tests/test_gui.py > /tmp/gui-e2-final.log 2>&1` 退出 0，`CHECKS total=1213 passed=1213 failed=0`；`ruff check .` 与 `git diff --check` 退出 0。均为 `6619cf5` 上未提交工作区的合成/数据无关层，不等于真实 MRI、真实数据全套或新模型验证。界面文字同步三视图编辑、来源轴状参考和显示重置语义。E2 允许进入 E3；工程包、跨次 Undo、自动保存尚未实现，不据此宣布整体交付。
- E3 存储核心，2026-09-07：新增纯逻辑 `project_store.py` 的捕获/保存/加载接口。单 ZIP 同时提交 manifest、各序列 NPZ、压缩历史及 summary CSV；临时文件 flush/fsync 后一次 replace，失败保留原件。恢复先建立全部离线序列，再验证来源接入，部分载入再保存不缩减其他序列与历史。保存快照共享只读数组，后续编辑按需复制被修改工作层，不逐次复制所有体积。已保存文档包括工作层、AI 只读层、置信度、普通标注和最近历史；当前仅在存储 API 验证，产品按钮/自动恢复尚未切换新格式。
- E3 校验与恢复：最终来源 digest、shape/dtype、可逆 affine、普通标注空间、图层引用独立校验；先读 NPY 头，拒绝巨型伪造 shape、pickle 和未登记数组，限制 ZIP/历史解压规模。最近历史在临时离线校验副本上逆向重放，错误不等到用户 Undo 时才暴露；这不能替代真实 DICOM 接入证明。仅历史错误时允许调用者明确请求恢复副本，新文档 ID/路径并记录原件哈希、原因和保护路径，不能覆盖原件。最终图层损坏拒绝此恢复方式。产品层的恢复选择界面尚未接入。
- E3 自动记录核心：CSV/manifest 记录病灶 ID、来源网格范围、体素数、类型未知/预测来源及修订状态；合成 CT 验证真实几何体积/HU，MRI 不伪造 HU 或类型。缺失来源时保留既有统计和计算时间，并标示缓存来源。保存捕获隔离、两序列逐步跨次 Undo、离线栈顶拒绝、原子替换失败、损坏副本和来源/空间/NPZ 负例均进入数据无关套件。
- E3 当前回归：`conda activate dicom_gui; SKIP_REAL_DATA=1 python tests/test_gui.py > /tmp/gui-e3-store-regression.log 2>&1` 退出 0，`CHECKS total=1241 passed=1241 failed=0`；`ruff check .`、`git diff --check` 退出 0。同一基线 HEAD 上未提交；模块清单同步为 23 / 14，`.miwproj` 和新输出目录加入忽略。28 项新增存储检查使用合成/临时输入，未运行真实模型。
- E3 产品接入，2026-09-07：保存/显式打开/按 Study 默认恢复已切换 `.miwproj`，目录由 QSettings 记忆；统一 revision 通知驱动 2 秒空闲/30 秒连续操作保存，单 Qt worker 合并最新请求。手工保存、切换检查、关闭等待最新完整保存；失败提供重试/换位置/留在当前/放弃选择，默认不丢工作。显式打开当前工程时先保存再重新读取，修复提前读取旧版本导致界面回退；换目录使旧回执失效，修复旧 worker 将目标路径改回旧目录。
- E3 恢复与边界：实际 UI 恢复副本保持独立 ID/路径和原件保护，默认恢复损坏工程不静默回退旧导出。合成两序列部分载入/再保存保留离线内容和栈顶 Undo；缺几何但身份可验证的原位参考与最近 20 次整卷 Undo 可跨次恢复。混合输入的无身份、无标注只读暂存不纳入包并提示，不阻断有效序列保存；含标内容却缺身份必须拒绝。此类来源也不启动器官 AI。旧 JSON 转换失败条目可见提示及原文件路径；旧 NPZ 只迁工作结果并记录导入哈希/时间，拒绝有损 dtype 转换。选择新目录已有同名文件时另取独立文件名，不覆盖原文件。
- E3 保存完整性：summary/recovery 结构与引用独立校验，CSV 必须对应 manifest 摘要；保存容量门覆盖数组/元数据/历史展开，提交前在共享数组校验副本逆向重放 Undo，防止成功保存不可恢复的历史。保存成功时间随工程恢复并显示，提示包含实际路径及 JSON/NPZ/CSV 格式。实际 Qt 鼠标按下期间后台保存不取消或保存半笔，松开仍只提交一个来源体素；合成 AI 回调无需手工编辑，真实 2 秒计时器即保存原始/工作结果，过期回调不修改 revision。
- E3 产品回归：`conda activate dicom_gui; SKIP_REAL_DATA=1 python tests/test_gui.py > /tmp/gui-e3-product-regression-4.log 2>&1` 退出 0，`CHECKS total=1256 passed=1256 failed=0`。此前第 3 轮因新增回调守卫访问轻量旧测试对象缺失属性而退出 1，已改为兼容缺省读取，未删除过期回调保护。上述通过后增加纯 AI/真实预览、部分载入产品链路及目录冲突 8 项定向检查，均通过；仍待最新统一回归。均为同一 HEAD 上未提交工作区、合成输入和假 AI 回调，无真实推理。
- E3 首次代表体积失败：合成 `233×512×512` CT，3 图层、有效置信度、初始 20 步混合历史，保存期间继续提交两次编辑。`QT_QPA_PLATFORM=offscreen python /tmp/gui_e3_resource_probe.py` 在 `dicom_gui` 中退出 1；两次 worker 保存合计超过拟定 120 秒队列预算，编辑刷新阶段 UI 最大心跳间隔超过拟定 0.5 秒预算。完整时间、峰值 RSS、模型为空、源码/脚本哈希、机器/依赖及输入身份记在 [原始失败记录](/Users/sc/01_Projects/GUI/Annotation_Projects/e3-resource-20260907T122107Z/run.json)，不改写为 PASS。首个启动尝试因沙箱拒绝读取 `hw.memsize` 在测试前退出，后续将物理内存记为未知，不声称占用比例；未升级权限。
- E3 性能定位与更正：[cProfile 记录](/Users/sc/01_Projects/GUI/Annotation_Projects/e3-profile-20260907T122435Z/run.json) 将仅两个手绘体素的刷新耗时定位到 `quantify` 对整卷背景计算 ndimage mean/SD。已将标签计数分块，并复用原本计算百分位所需的标签样本，以 float64 计算相同总体均值/SD；原手算、高标签、置信度回归继续通过。旧性能探针还用连续 `QTest.qWait` 轮询后台 Python worker，改为与产品一致的 `QEventLoop.exec` 后复核。因统计实现和等待方式同时改变，旧保存耗时不作为产品基线，不宣称某个保存加速倍数；这不是提高或取消原预算。
- E3 代表体积复核通过：[最终运行记录](/Users/sc/01_Projects/GUI/Annotation_Projects/e3-resource-20260907T122720Z/run.json) 与同目录 `probe.py` 固定输入配方、机器/环境、源码/脚本/工程哈希及结果。上述相同体积/图层/历史工作负载，Qt worker 串行两次保存、最终 revision/两次新编辑/最近 20 步完整恢复、UI 心跳间隔 ≤0.5 秒、全过程 peak RSS ≤4 GiB 六项均通过，命令退出 0。该一次合成配置不能证明任意体积、20 次稠密整卷差分或同时多模型推理资源上限；缺模型权重时不报告模型性能。
- E3 阶段行为回归：`conda activate dicom_gui; SKIP_REAL_DATA=1 python tests/test_gui.py > /tmp/gui-e3-product-final.log 2>&1` 退出 0，`CHECKS total=1264 passed=1264 failed=0`；`ruff check .`、`git diff --check` 退出 0。同一 HEAD 上未提交工作区；23 / 14 模块登记与 known-bad 缺模块守卫保留。E3 当前编辑/保存范围允许进入 E4，整体目标未完成。
- E4 核心，2026-09-07：新增纯模块 `series_registration.py`，同检查来源/空间绑定与 FrameOfReference 一致时提供元数据定位；不把同 FrameOfReference 写成运动已验证。三维适配使用本机已安装的 SimpleITK 2.5.3，按已批准方案同步三份应用依赖声明，未执行安装或升级。采用 Euler3D/Mattes MI、多分辨率和固定采样 seed，限制输入尺寸/迭代/时间；SimpleITK fixed→moving 在边界求逆为持久化的 moving→fixed LPS。无几何、无重叠、恒定强度、不合理变换及取消返回明确失败；数值门通过仅产生 candidate。
- E4 空间与事务验证：真实写盘/读取的非对称合成 MR，包含各向异性、15° 斜采集、三轴旋转/平移和非线性强度差异；独立空间标志点 <1 mm 门通过。标志点错误拒绝采用，candidate 不能用于正式对应；反向定位使用同一变换的逆。配准结果版本与采用分开，纯结果接入递增 revision；采用/撤回与像素编辑共用顺序 Undo。变换/方向/参数/质量/来源及采用状态随工程恢复，离线栈顶要求两端重新接入，非刚性伪造矩阵即使重算摘要也被拒绝。核心回归 `/tmp/gui-e4-core-regression.log` 为 `CHECKS total=1283 passed=1283 failed=0`，退出 0。
- E4 产品接入：实际 Qt worker 计算候选，经三面当前/变换后参考/叠加对照窗口明确采用后另记人工复核版本，不冒充标志点验证。结果与采用无需手绘即自动保存；跨次可按统一 Undo 撤回采用，原始结果和来源 mask 保留。切换序列定位到同一患者位置；参考序列 mask 以 nearest-neighbor 只读显示，患者空间对象变换后显示，原位/all 参考不伪造跨序列位置。旧二维随访配准未替换。晚到/取消/关闭/输入 revision 改变时拒绝回调且安全等待线程退出。真实产品入口、自动保存和上述生命周期测试通过。
- E4 当前回归：`conda activate dicom_gui; SKIP_REAL_DATA=1 python tests/test_gui.py > /tmp/gui-e4-product-regression.log 2>&1` 退出 0，`CHECKS total=1289 passed=1289 failed=0`；`ruff check .`、`git diff --check` 退出 0。模块登记为 24 / 15，known-bad 缺模块守卫继续通过。Qt 三面复核窗口的三个滑条已驱动 9 幅预览，截图检查及 `1280×800` 主窗口检查使用合成数据，不算真实 MRI 支持证据。所有实现仍在同一 HEAD 的未提交工作区。
- E4 外部输入：官方 TCIA collection 页仍可核实 PROSTATE-DIAGNOSIS 为 MR/DICOM、CC BY 3.0，但 NBIA 序列级只读查询未成功（web 读取失败；本地 urllib 被沙箱网络拒绝，未升级权限），尚无法确认具体同检查序列、Classic MR 类型与单例大小，故未下载影像。已通过异步问题询问用户是否有本地去标识多序列 Classic MR 目录；未收到输入前不宣称 E4 全部通过。集合级 5.67 GB 不能当作已确定的单例下载成本。[官方集合说明](https://www.cancerimagingarchive.net/collection/prostate-diagnosis/)
- E4 边界补验，2026-09-07：发现复核窗口把来源数组轴当作患者解剖平面滑动轴。合成矢状采集的三个真实 Qt 滑条均未覆盖目标范围，首轮定向检查 `5 项 / 3 失败`、退出 1；新增纯函数 `patient_plane_cursors`，按患者包围盒和法向采样后修复。随后发现预览把异方性像素当正方形，三个物理宽高比检查均失败（`8 项 / 3 失败`、退出 1）；按物理尺寸缩放后 `8/8`、退出 0，包含实际采用/取消按钮点击。中间首次修复还暴露缺少平面常量 import，已修正；未将这些失败写成通过。
- E4 不同网格验证：已知三轴刚性变换、两端不同 shape/spacing/IOP 的合成 MR，双向光标定位、整面 nearest-neighbor 高标签与独立标量患者坐标 oracle、普通标尺真实平面交点、二维参考拒绝投影共 `4/4`、退出 0。来源数组/普通对象不被改写。此处验证对应采样，不是新的真实 MRI 配准精度结果。
- E5 文档：已更新 `docs/manual_zh.md / manual_en.md` 的图层、单体素、统一 20 步 Undo、全部序列保存、2 秒/30 秒自动保存、离线来源、恢复副本、旧格式只读迁移与 MRI 复核操作；README 同步当前开发范围与模块数。保留 V1.0 PDF 和历史研究证据。SimpleITK 2.5.3 上游 Apache-2.0 声明核查后补入 `THIRD_PARTY_NOTICES.md`，没有改变本仓库许可或执行依赖安装。[版本化上游页面](https://pypi.org/project/simpleitk/2.5.3/)
- E5 真实 CT 定向闭环：`conda activate dicom_gui; python` 通过 `runpy.run_path('tests/test_gui.py')` 调用 `test_real_ct_annotation_project(QApplication([]))`，日志 `/tmp/gui-e5-real-ct-project-2.log`，`CHECKS total=11 passed=11 failed=0`，退出 0。使用原始公开 `肺癌/` 233 层，只读输入，工程写入 TemporaryDirectory；实际按钮/鼠标/键盘验证肺窗预览、三面单来源体素、完整保存/显式重开/Undo、重置保留结果与原模体 FBP 入口，禁止启动整卷器官推理。首轮 `/tmp/gui-e5-real-ct-project.log` 为 `9/11`、退出 1：初始本就是肺窗，且测试误把仅供链式重建的 `_last_recon_img` 当 FBP 产物；改为明确从纵隔窗切肺窗、检查产品实际提交至 V4 的 FBP 数组后通过。没有改动产品迎合错误断言；定向检查不等于本地全套回归。
- 验证口径更正：早先 E3/E4 回归记录中的“无真实推理”只能用于新增的合成 AI 回调用例，不能概括整个现有套件。已重新读取 `/tmp/gui-e3-product-final.log` 和 `/tmp/gui-e4-product-regression.log`，其中 `test_dl_recon_guard` 明确记录已有 CNN 重建权重就绪并执行小型数组推理断言。本轮 `/tmp/gui-e4-e5-regression.log` 同样如此（`1298/1298`、退出 0，尚未包含后加的 3 个预览比例检查）。没有运行新肿瘤模型或整卷器官推理；没有据此报告性能指标。原始日志保留，撤回此前对整套测试无推理的概括。
- E4/E5 最新数据无关门：`conda activate dicom_gui; SKIP_REAL_DATA=1 python tests/test_gui.py > /tmp/gui-e4-e5-final-subset.log 2>&1`，`CHECKS total=1301 passed=1301 failed=0`，退出 0；`ruff check .` 与 `git diff --check` 退出 0。包括修复后的三面滑动/比例及文档一致性；真实 CT 的 11 项只在本地全套分支登记，本轮按上条命令独立执行，不混入 1301 分母。基线 HEAD 仍为 `6619cf5edec75ea1c831f243a9b438ba81064a3d`，所有修改未提交，无新远端 CI 证据。
- E5 全套首次验收：`python -u tests/test_gui.py > /tmp/gui-e5-full-regression.log 2>&1` 退出 1，1424 项中 1419 通过、5 失败。真实 CT 共享 fixture 已使用 TemporaryDirectory 作为工程/旧缓存目录，关闭自动保存，禁止整卷器官推理；仍保留已有小规模 CNN 重建检查。失败分类：平面直接赋值未刷新映射、ROI 两项仍检查被事务替换的旧对象、新患者空间渲染未跳过畸形条目、README 自证摘要未同步。
- E5 修复与 RED/GREEN：新合成容错用例复现 4 项中 2 失败（退出 1），修复后 4/4、退出 0。患者空间坐标须是非空有限 LPS 三元组；渲染逐条跳过坏容器/对象，后续有效标注仍显示。MPR 测试改经真实平面控件；ROI 经标注信号创建并检查文档提交，补实际 Undo 按钮按序恢复尺寸/位置，不要求旧字典原地变动。真实 CT 定向回归 18/18、退出 0；首次定向测试误用了不存在的测试调用 `undo_annotation`，已改用实际 `btn_undo.click()`，不新增产品别名。旧 JSON 容错夹具退出时恢复临时目录属性。
- E5 最终回归：在 `dicom_gui`、基线 `6619cf5edec75ea1c831f243a9b438ba81064a3d` 的未提交工作区运行 `python -u tests/test_gui.py > /tmp/gui-e5-full-regression-2.log 2>&1`，`CHECKS total=1430 passed=1430 failed=0`，退出 0；随后 `SKIP_REAL_DATA=1 python -u tests/test_gui.py > /tmp/gui-e5-final-subset.log 2>&1`，`CHECKS total=1305 passed=1305 failed=0`，退出 0。`ruff check .`、`git diff --check` 均退出 0。增加的 6 项为合成容错 4 项、全套 ROI 顺序 Undo 2 项；没有删除原失败保护。`docs/project_report_zh.md` 仅依原 canonical command 同步 README diff SHA-256 为 `67d765ada79ff224b55536c79bdd4b3d793deed1be5139f3544858fc4ed314a5`，保留原 baseline，不改冻结 PDF。
- E5 留存证据：[checks.json](/Users/sc/01_Projects/GUI/Annotation_Projects/e5-regression-20260907/checks.json) 记录全套前后、容错 RED/GREEN、定向与子集日志摘要/退出码/分母，以及最终源码文件哈希。同目录保留对应日志；这是本地工作区验证，不是 clean-clone、已 commit 或 remote CI。真实输入只有已有公开 CT，MRI 仍为合成；没有运行新肿瘤模型或整卷器官推理。
- R1 结案：候选池 12/12、组合路线 3/3，新增 BRISC 作者最新版明确患者划分局限；固定 BiomedParse 与 Raidionics 代码版本，核对后者具体模型 release/asset 身份及许可，保留不可证明的权重摘要/CPU/联合指标空缺。结果及重新启动条件集中在第 5 节；不进入 R2–R4，不把模型名称/预设 prompt/序列分类当瘤种识别。
- 2026-09-07 历史断点（已由下方 2026-09-08 获取与验收替代）：当时缺少获准同次静态 Classic MR 多序列输入，不能用既有回归 PASS 替代真实 MRI 验收。

- E5 最终核对发现并补齐：计划要求不同序列可关联同一 lesion ID，但原实现只生成各自 UUID。现有 `create_lesion_command` 增加从同 Study 已连接病灶工作层建立同 ID 空层的操作；UI 新增「关联参考病灶」，要求空间对应可靠，拒绝器官、自身/未知来源及重复关联。沿用创建事务的 Undo/保存，不复制 mask、不转移模型置信度或类型结论；统计仍逐序列记录。核心初始 RED 因入口不接受参数退出 1，UI RED 因缺按钮退出 1；完成后的核心/实际按钮及重开检查共 11/11、退出 0。中英文手册与架构同步。补齐关联后的中间全套 `/tmp/gui-e5-linked-full.log` 为 1441/1441、退出 0。
- E5 笔画验收补强与真实缺陷：三面各在 0°/30° 采集进行实际纵横拖画、整笔 Undo、Cine 停止，并在笔画中换工具/平面/滚轮/序列。首轮测试误用不存在的工具按钮键，改用 `tool_btn_group.button(TOOL_RULER)` 后，出现不稳定的提前取消。调用栈 `/tmp/gui-e5-stroke-trace-2.log` 证实 `change_view_plane` 的 20ms `fitInView` 回调晚于开始绘制到达，调用 `cancel_interaction`。新增 `fit_if_idle` 保护，换面 20ms 与加载 100ms 的延迟适配均不打断新绘制/调窗或覆盖用户缩放；显式 resize/导航仍按原契约取消预览。
- E5 回归门自证：定向正常路径 `/tmp/gui-e5-stroke-navigation-green.log` 26/26、退出 0；在独立测试进程中仅把 `fit_if_idle` 替换为原无条件适配，`/tmp/gui-e5-deferred-fit-known-bad.log` 为 26 项中 8 项失败、退出 1，失败落在 Coronal/Sagittal 的整笔提交与预览维持，证明新检查能抓住目标退化。该替换没有写回产品文件。
- E5 最新全套：`conda activate dicom_gui; python -u tests/test_gui.py > /tmp/gui-e5-audit-full.log 2>&1`，1467/1467、退出 0；`SKIP_REAL_DATA=1 python -u tests/test_gui.py > /tmp/gui-e5-audit-subset.log 2>&1`，1342/1342、退出 0。比前一轮增加关联 11 项与笔画上下文 26 项。全套启动后仅清理了 `interaction.py` 已无用途的 `Qt` import；子集与最终 `ruff check . / git diff --check` 在清理后通过。行为代码在两次运行间一致。证据与源码绑定见 [最新 checks.json](/Users/sc/01_Projects/GUI/Annotation_Projects/e5-final-audit-20260907/checks.json)，旧证据目录保留。
- E4 输入阻碍复核：重新读取项目全部 `.dcm` 的 Modality/SOPClassUID，只有 `肺癌/` 与 `RIDER_HU_declared/` 各 233 帧 Classic CT，没有 MRI。PROSTATE-DIAGNOSIS 官方集合页本轮两次返回 500；搜索缓存仍只提供整集合信息，不能证明具体同 Study 的 Classic MR 序列/下载体积，先前 NBIA 失败未被绕过。没有下载数据，也不把未知下载范围作为可执行授权申请；仍需用户已有的去标识 MRI 目录，或可核实的单例公开数据访问恢复。
- Goal 阻塞审计（2026-09-07）：同一真实 MRI 输入缺失已持续至少三个连续 Goal 工作轮次；独立工程修复、回归和 R1 已交付，当前没有运行中的验证任务可等待。最新复核在 `dicom_gui` 中逐项对比 `e5-final-audit-20260907/checks.json` 的 `final_source_sha256`，无不匹配；用 `rg --files --hidden --no-ignore -g '*.dcm' -g '!**/.git/**'` 枚举并以 pydicom 读取 Modality，仍仅两目录各 233 CT、读取错误 0，命令退出 0。未重复运行回归或推理。Goal 标记 blocked，不标记完成；恢复条件是提供获准的同患者、同 Study 静态 Classic MR 多序列目录，或取得可核实的公开单例输入及其获取授权。代码仍未提交，不改变第 4 节验收范围。

### 2026-09-08 公开 MRI 输入筛选与获取

用户授权子代理评估和本任务总下载 20 GB 内自主获取后，三路只读预审覆盖 24 项候选；这是已找到并核查的范围，不声称穷尽全球数据集。集合页面大小仅用于预审，实际下载按单例序列清单及累计字节控制。模型研究 R1 已结案；下列输入筛选为 E4 工程验收，不把单瘤种/健康器官数据当完整肿瘤识别验证。

| 候选及官方出处 | 预审结论 |
|---|---|
| [PROSTATE-DIAGNOSIS](https://wiki.cancerimagingarchive.net/display/Public/PROSTATE-DIAGNOSIS) | **实际选用**：NBIA v4 核实 ProstateDx-01-0001 同 Study 三静态序列 T1W_TSE_AX / T2W_TSE_AX / T2W_TSE_COR，CC BY 3.0。原文件 21,083,244 字节；已下载并逐帧检查 Classic MR、Study/Series/Patient/SOP、完整图像数。未取 DCE。 |
| [Vestibular-Schwannoma-SEG](https://www.cancerimagingarchive.net/collection/vestibular-schwannoma-seg/) | **已选用的空间补充**：ceT1 + hrT2、CC BY 4.0，附官方 fiducial 注册 TFM 与原空间轮廓。VS-SEG-001 同 Study 两 MR 序列、200 单帧，原文件 87,251,900 字节，已获取并完成下方限定验收；不取约 28.19 GB 全集合。单瘤种不能验证跨瘤种识别。 |
| [CHAOS](https://zenodo.org/records/3431873) | 腹部备选：T1-Dual + T2-SPIR DICOM，训练包 890,771,694 字节；官方 API 许可为 **CC BY-NC-SA 4.0**。双回波须分开，Study/SOP 仍待实物核实；健康腹部不提供肿瘤分类证据，未下载。 |
| [Prostate Fused-MRI-Pathology](https://www.cancerimagingarchive.net/collection/prostate-fused-mri-pathology/) | 静态 T1/T2 候选，影像 4.74 GB、CC BY 3.0；无需下载 76.8 GB 病理。未核具体单例，暂不取。 |
| [PROSTATE-MRI](https://www.cancerimagingarchive.net/collection/prostate-mri/) | 26 人多序列 DICOM 约 3.4 GB、CC BY 3.0，2018 已取消限制；部分 DWI 标签缺失，优先结构像。未核具体静态双序列。 |
| [PROSTATEx](https://www.cancerimagingarchive.net/collection/prostatex/) | 多参数 DICOM 可按病例取；Ktrans 为 MHD/ZRAW，不能代替原始 DICOM。具体静态序列与身份仍待查。 |
| [QIN-PROSTATE-Repeatability](https://wiki.cancerimagingarchive.net/display/Public/QIN-PROSTATE-Repeatability) | 14.86 GB、CC BY 4.0；2020 已解除限制。必须在同 Study 内取结构序列，不将 test/retest 两次检查冒充同次。不带 Repeatability 的 QIN PROSTATE 仍需账户/申请，是不同集合。 |
| [TCGA-PRAD](https://wiki.cancerimagingarchive.net/pages/viewpage.action?pageId=6884022) | CT/PT/MR 混合 3.74 GB、CC BY 3.0；缺具体同 Study 双结构 MR 证明，低优先。 |
| [Prostate-MRI-US-Biopsy](https://www.cancerimagingarchive.net/collection/prostate-mri-us-biopsy/) | v2 新增 ADC/high-b DWI，不能沿用旧版“仅 T2”；仍不保证静态结构双序列，全量约 79.61 GB 不取。 |
| [Prostate-3T](https://wiki.cancerimagingarchive.net/display/Public/Prostate-3T) | 每患者单 T2 序列，不满足本次多序列正例。 |
| [Vestibular-Schwannoma-MC-RC](https://www.cancerimagingarchive.net/collection/vestibular-schwannoma-mc-rc/) | v2 14.25 GB、CC BY 4.0；只有部分时间点双 T1/T2，必须查同 Study，作为后备。 |
| [UPENN-GBM](https://www.cancerimagingarchive.net/collection/upenn-gbm/) | DICOM 可取病例，当前页 CC BY 4.0；Study/Series 分组需实查。预处理 atlas NIfTI 不能直接叠加原空间，不优先本次工程。 |
| [Brain-Tumor-Progression](https://www.cancerimagingarchive.net/collection/brain-tumor-progression/) | 多序列 DICOM 约 3.16 GB，但当前页 NIH Controlled Data Access Policy，预算授权不代替访问许可，排除直接获取。 |
| [REMBRANDT](https://www.cancerimagingarchive.net/collection/rembrandt/) | 多序列 DICOM 约 10.59 GB，当前影像受控；不沿用旧 CC BY 记录直接取数。 |
| [UCSF-PDGM](https://wiki.cancerimagingarchive.net/pages/viewpage.action?pageId=119705830) | 官方预处理 NIfTI，不提供原 DICOM；不满足当前导入验收，保留未来 glioma 研究价值。 |
| [BraTS2021](https://www.cancerimagingarchive.net/analysis-result/rsna-asnr-miccai-brats-2021/) | 分割任务 NIfTI，MGMT 任务有 DICOM；不能笼统称全部 NIfTI。预处理、来源/UID 与许可混合，不作首个原空间工程正例。 |
| [IXI](https://brain-development.org/ixi-dataset/) | 健康多对比 MRI，但官方仅 NIfTI，不满足真实 DICOM 验收。 |
| [Soft-tissue-Sarcoma](https://www.cancerimagingarchive.net/collection/soft-tissue-sarcoma/) | T1 与 T2FS/STIR、9.87 GB、CC BY 3.0，备选；必须排除已配准到 PET 的 Aligned 派生像，单例未实查。 |
| [BREAST-DIAGNOSIS](https://www.cancerimagingarchive.net/collection/breast-diagnosis/) | 通常 T2/STIR/BLISS，CC BY 3.0；筛静态 T2/STIR，排除动态 BLISS。全量 60.87 GB 不取。 |
| [CPTAC-CCRCC](https://www.cancerimagingarchive.net/collection/cptac-ccrcc/) | CT/MR、CC BY 4.0；未证明具体同 Study 双结构 MR，条件备选，不为筛选整库下载。 |
| [Advanced-MRI-Breast-Lesions](https://www.cancerimagingarchive.net/collection/advanced-mri-breast-lesions/) | 可筛 T2/T2FS，CC BY 4.0；TRAM 是 Secondary Capture，不能作 Classic MR，集合 645.62 GB 不取。 |
| [Duke-Breast-Cancer-MRI](https://www.cancerimagingarchive.net/collection/duke-breast-cancer-mri/) | CC BY-NC 4.0；官方提示 FrameOfReferenceUID 被 dummy 替换，不作首个元数据定位正例。 |
| [OsiriX DICOM 示例](https://www.osirix-viewer.com/resources/dicom-image-library/) | WRIX 等小型真实 MRI 样例，但当前需 Premium Membership；不采用旧“免费”印象，不找镜像绕过。 |
| [QIN-SARCOMA](https://www.cancerimagingarchive.net/collection/qin-sarcoma/) | 主要 DCE/纵向数据，没有两套静态结构序列证据，排除本次正例。 |

获取实测：官方 [v4 schema](https://cbiit.github.io/NBIA-TCIA/nbia-api.yaml) 指明 `https://nbia.cancerimagingarchive.net/nbia-api/services/v4/`，只读 `getSeries / getDicomTags` 已成功；本机沙箱普通网络报 Operation not permitted 后，经自动审批允许只读/已授权下载网络请求，未绕过访问许可。此前旧入口失败不再作为“公开 MRI 不可获得”的结论。

前列腺输入及验收：[acquisition.json](/Users/sc/01_Projects/GUI/Annotation_Projects/e4-real-mri-20260908/acquisition.json)、[input-validation.json](/Users/sc/01_Projects/GUI/Annotation_Projects/e4-real-mri-20260908/input-validation.json)。92 张单帧 MR，三序列原始 shape 分别 36×320×320、32×400×400、24×256×256，含斜采集和真实冠状采集，来源/空间绑定均成立，读取 warnings 为空。`conda activate dicom_gui; python -u Annotation_Projects/e4-real-mri-20260908/accept_prostate.py` 经实际 Qt 鼠标/控件执行三序列三面单体素、跨序列 LPS 定位、全部标记保存、重开 Ctrl+Z，21/21、退出 0；逐文件/解码卷哈希保持不变，未启动模型。[验收 JSON](/Users/sc/01_Projects/GUI/Annotation_Projects/e4-real-mri-20260908/gui-acceptance.json) 同目录保留脚本、日志和截图。初次只读探针误查不存在的 `SeriesVolume.capabilities` 导致退出 1，改用实际 `intensity_unit / geometry / source_binding / affine` 字段后验证，不新增产品属性。此时尚不宣称真实图像刚性配准准确，继续 VS-SEG 独立空间参考。

最终真实空间与证据审计（2026-09-08）：

- 三路子代理完成候选评估，独立审计指出“勾选参考层/截图”不能证明实际对应显示，已补实际非空只读 overlay 与独立 LPS→来源体素逐像素一致性。首次补验漏选来源活动工作层，第二次错误假设 autosave=False 的关闭会自动保存；均作为验收夹具失败保留，不改产品以迎合断言。最终通过真实控件选图层、明确点击保存；[补验脚本及 JSON](/Users/sc/01_Projects/GUI/Annotation_Projects/e4-real-mri-20260908/reference-acceptance-v3.json) 6/6、退出 0。参考图层标记是明确的测试标记，不冒充真实瘤范围。
- VS-SEG-001 官方 TFM 的方向按[作者固定提交](https://github.com/KCL-BMEIS/VS_Seg/blob/33410a2d44e3f57b4df1c3ed005e6d40c0824aa6/preprocessing/data_conversion.py#L186-L190)解释：文件为逆变换，SimpleITK 读取后求逆得到前向 LPS 点映射。与双原空间 JSON 的 1093 个对应轮廓点核对方向。JSON 的 T2 点由官方变换派生，不是 1093 个独立解剖标志点，不能据此报告临床配准准确率。
- 真实 GUI 按钮启动 CPU 配准：T1→T2 全采样 MI 从 -0.5984867342801823 到 -0.598189542190485，变差后按原质量门拒绝；首轮预期成功的验收因此退出 1，原日志与诊断保留。未松动质量阈值。反向 T2→T1 返回 candidate，在同一外部 fiducial 参考下轮廓点位置最大差异 0.3292528854300824 mm，小于原 2.5 mm 门槛；[反向验收](/Users/sc/01_Projects/GUI/Annotation_Projects/e4-real-mri-20260908/vs/reverse/registration-acceptance.json) 7/7、退出 0。只代表该病例、该方向、该位置范围的外部变换一致性。
- 复核对话框三面 25%/50%/75% 位置截图已检查，T2 小视野以外显示空白，不伪造延伸内容。实际 candidate 保留未采用状态，未冒充人工临床复核；补验将真实 worker 输出重新绑定同源 MRI，通过 Save→读取工程逐字段比对变换、来源及质量，确认落盘且 active links 仍为空。原 7/7 中“persisted”仅由内存断言支持，现由单独 6/6 补验补足磁盘证据。
- [最终 checks.json](/Users/sc/01_Projects/GUI/Annotation_Projects/e4-real-mri-20260908/checks.json) 汇总所有成功/失败日志、退出码、输入/源码/产物哈希与机器配置。已记录下载 82,408,868 字节，另为早期小型只读元数据响应保留 10 MB 预算余量；原始 DICOM 共 292 张、108,335,144 字节。总量远低于授权的 20 GB。两份 acquisition、全部原始 DICOM 以及既有 E5 源码/日志哈希重新校验，零不匹配。`ruff check .`、`git diff --check` 退出 0。数据/证据留在忽略目录，没有提交、推送或新 remote CI。

### 最终验收对照（2026-09-08，按本计划范围完成）

2026-09-08 输入获取授权：用户要求广泛查找数据集并开子代理评估，明确本任务 20 GB 内可直接下载。由主代理集中下载与记账，三个子代理只读筛选脑部、前列腺和其他结构 MRI；总量按十进制 20,000,000,000 字节上限控制，不按每个数据集分别放宽。优先少量完整同 Study 多序列病例，元数据、压缩包和实际解压规模分别记录；数据仅存被忽略的 `Annotation_Projects/`，不改原始数据。授权解决下载确认条件，不代表绕过受控访问、安装依赖、接受新协议或启动肿瘤模型训练/推理。官方 TCIA API 文档现列 v4；已读取其 schema，后续按官方参数核实单例格式和成本。历史 blocked 记录保留，但不再作为当前停止原因。

逐项对照第 4 节必测行为及当前测试的实际断言。下表的工程验证以本地合成输入/既有 CT 为范围，测试入口均位于 `tests/test_gui.py`；不把单个纯函数用例当整套 GUI 流程证据。新发现的病灶关联入口缺失与延迟适配取消笔画问题已单列修复，须以其后回归记录为准。

| 必测项 | 主要实现/实测入口 | 核对结果与限制 |
|---|---|---|
| 1：坐标、单体素、边界 | `patient_plane / stroke_voxels`；`test_pixel_transform_boundaries / test_document_pixel_gestures` | 实际 Qt 三面点击，含 30° 斜采集、异方性、缩放平移、边界拒绝；不是仅比较数组 shape |
| 2：混合顺序 Undo | `EditCommand / EditHistory`；`test_document_ordered_undo / test_document_spatial_annotations / test_roi` | 混合序列的像素/标尺、真实 ROI 拖动缩放和批量 Delete；另测 20 步整卷撤销及置信度还原 |
| 3：编辑期间换上下文 | `_capture_edit_context / cancel_interaction`；`test_drawing_context_audit / test_stroke_navigation_contract` | 工具、平面、滚轮、序列和模式切换取消预览，释放不误写其他来源；新用例暴露并修复了晚到自动适配的问题 |
| 4：完整保存/有效空状态 | `capture/load_project_snapshot`；`test_project_store_roundtrip / test_viewer_project_roundtrip / test_registration_storage_and_history` | 同包保存各序列图层、普通对象、历史与变换；原始 AI 保留、工作层可恢复为空。新增 `test_linked_lesion_identity` 补共享 ID 的跨序列独立范围与重开 Undo |
| 5：错身份/坏包拒绝 | `_validate_binding / _validate_history_commands`；`test_series_source_binding / test_project_final_validation / test_mask_cache_guard` | 相同 UID/shape 而像素不同、重复 SOP、旧轴约定/指纹、schema/尺寸/历史边界均有拒绝用例 |
| 6：失败和保存期间变化 | `ProjectSaveWorker / _prepare_document_leave`；`test_project_atomic_and_partial / test_viewer_autosave_queue / test_viewer_leave_save_failure` | 注入替换/写入失败，旧包字节保留；新变更不被旧保存回执清 dirty；关闭或切检查可取消离开 |
| 7：晚到回调 | generation/document ID/revision 守卫；`test_document_ai_lifecycle / test_viewer_save_directory_race / test_viewer_registration_cancellation` | 旧 AI、保存及配准结果不能覆盖后续文档或修改；独立结果版本不清人工历史 |
| 8：MRI/CT 能力隔离 | `SeriesVolume / _apply_series_capabilities`；`test_series_source_binding / test_multiseries_viewer_loading` 及既有 CT 守卫 | 合成 MRI 保留 stored intensity、不伪造 HU，不送 CT 专用路径；既有真实 CT 的旧功能单列全套 |
| 9：配准成功与拒绝 | `register_rigid_3d / verify_landmarks`；`test_series_rigid_registration / test_registered_cross_grid_annotations` | 独立已知刚性变换/标志点、不同网格对应、无重叠/错位/取消负例；优化候选不能自动等同验证成功 |
| 10：真实 CT + MRI | `test_real_ct_annotation_project`；`accept_prostate.py / accept_reference.py / vs/accept.py` | **已补齐**：既有真实 CT 闭环；真实前列腺三序列/三面编辑、保存重开/Undo 21/21；只读对应层及真实配准候选落盘补验 6/6；VS 反向参考一致性 7/7。正向配准拒绝记录保留，不宣称双向或临床普适通过 |
| 11：部分来源载入 | `attach_sources / load_project_snapshot`；`test_viewer_partial_project_preservation / test_project_atomic_and_partial` | 离线序列、缓存统计和历史随全包保留；栈顶来源离线不跳步。身份改变由绑定拒绝用例覆盖 |
| 12：旧结果迁移 | `_load_saved_mask / _load_annotations_json`；`test_mask_cache_roundtrip / test_project_raw_and_history_limit` | 旧工作 mask 不补造原始 AI 或迁移前 Undo，旧 `all` 维持二维参考；文件只读，未转换项明确报告 |
| 13：原位编辑绑定 | `_source_binding`；`test_series_source_binding / test_project_raw_and_history_limit / test_unbound_source_disables_editing` | 分别缺空间标签仍保来源身份，原位保存/20 步重开 Undo；身份缺失在编辑入口拒绝，没有伪毫米数据 |
| 14：完整鼠标笔画与对照 | `test_stroke_navigation_contract / test_document_ai_lifecycle / test_viewer_ai_autosave_and_preview` | 新增 0°/30° 三面纵横拖画、Cine 停止、单步提交/整笔 Undo；保存只读完整提交，不含半笔；原始 AI 只读且后续版本不覆写人工层 |
| 15：历史损坏恢复副本 | `load_project_snapshot(recover_history=True)`；`test_project_history_recovery / test_viewer_open_and_recovery` | 最终数据校验通过才允许独立副本；原件不覆盖，连接来源后继续保存副本；最终数据坏不准普通恢复 |
| 16：纯自动结果落盘与对比隔离 | `test_viewer_ai_autosave_and_preview / test_viewer_registration_worker / test_viewer_autosave_queue / test_study_candidate_loading` 及对比加载守卫 | 真实计时器保存合成 AI/配准结果；过期回调不改状态，最新保存请求合并；独立候选读取不污染主工程 |

额外边界：Classic CT/MR 单帧的输入守卫与明确错误信息仍在；新增顶层模块 24/纯逻辑 15 的声明/架构一致性及 known-bad 缺模块门保留。工程包/导出目录继续被 `.gitignore` 排除。Markdown 使用说明可更新，登记 PDF、旧导出和实验产物未改动。R1 已交付有限候选证据和缺口，R2–R4 未授权启动，模型性能与真实分类准确性不在本轮 PASS 声明内。

### R2 试跑准备（2026-09-08，方案已具体化，尚未安装或推理）

用户同意继续准备下一轮模型试跑；20 GB 授权仍仅覆盖公开数据获取。本节是待执行方案，不代表新增依赖、模型权重或昂贵推理已经获准。推荐先做一次独立 CPU 可行性探针，保留原工作站环境与 E0–E5 验收基线。

**当前已核实的准入条件：**

- 首选 BiomedParse v2，代码固定为 [`e02096c03af0d79c6994ffc2d60a49eeb0361e1f`](https://github.com/microsoft/BiomedParse/tree/e02096c03af0d79c6994ffc2d60a49eeb0361e1f)。[官方权重目录](https://huggingface.co/microsoft/BiomedParse/tree/main)列 `biomedparse_v2.ckpt` 为 4.46 GB，模型页许可为 CC BY-NC-SA 4.0，与代码 Apache 2.0 分开处理。当前访问要求登录并同意分享联系信息，实际文件页面返回 401；尚无权重字节、不可变版本或 SHA256。由用户自行完成官方访问手续，不索取聊天中的 token，不找镜像绕过。
- 固定代码 requirements 使用 `torch==2.6.0+cu124` 等 CUDA 版本，README 另要求 Detectron2；不能直接在 Apple Silicon 执行原安装清单。当前 `dicom_gui` 为 torch 2.11.0、numpy 2.2.6，且缺 hydra-core、transformers 等。建议授权后在忽略目录创建独立 Python 3.10 环境，先解出原版本对应的 CPU/macOS 依赖并锁定，不升级现有环境。推理文件直接依赖 Detectron2、fvcore、timm、safetensors；已读 pixel decoder 中 DeformConv 仅出现在 import，尚不能据此证明整个导入链无需编译。环境导入失败时记录并停止，不临时改模型算子求通过。
- 语言配置还通过 `AutoTokenizer.from_pretrained` 获取 `openai/clip-vit-base-patch32` tokenizer；文本 encoder 的 `LOAD_PRETRAINED=false`，没有证据要求另外下载整套 CLIP 权重。须固定 tokenizer revision、文件和哈希，并禁止推理阶段隐式联网。
- 独立 runner 应按实际目录使用 `configs/model/biomedparse_3D`，传入已核实的 v2 权重路径；原 inference.py 的 config 路径和示例 checkpoint 名称不能直接照搬。原加载器 `strict=False`，成功打印不算验证；必须记录并审查 missing/unexpected keys，未证明匹配则停止。不能为加载未知对象直接放宽反序列化限制。

**建议的单次授权包与顺序：**

1. 新环境、源码、模型及 tokenizer 下载合计上限 8 GB（与现有数据预算分账）；保留文件清单/版本/哈希，禁止上传病例、GPU、云计算和训练。若依赖解析预计超过上限或需更改模型结构，停止并报告具体缺口。
2. 先做 CPU 导入及权重完整加载，再用现有 VS-SEG-001 T1 完整 120 层验证。使用原 DICOM 和官方原空间 TV 轮廓作输入/参考；准备 numeric NPZ 与独立 JSON，记录原始强度百分位归一化、轴映射、LPS affine、来源 UID/哈希和逆映射。先验证坐标往返，再启动模型。原始文件不改动，禁止根据模型输出调参考轮廓。
3. CPU 4 threads、slice batch size 1，单次模型子进程最多 15 分钟，进程树 RSS 采样上限建议 **12 GiB**。这是对原“最多 8 GiB”建议的待批准修订：已知 checkpoint 4.46 GB，加载时可能并存参数和 state dict，原上限可能在加载阶段耗尽；12 GiB 仍低于本机 32 GiB 的一半。这是监控停止阈值，不声称 macOS 提供无瞬时超调的硬内存隔离。触限即终止，不自动提高预算。
4. 首次只回答能否加载、完整处理一例、把预测准确映射回原空间以及时间/内存是否可接受。固定候选查询后记录各候选响应、重叠和空结果，病例标签不能进入自动类别选择逻辑；查询写着某瘤种、输出非空，不算识别成功。单类 VS 病例只能做探索性组件检查，不能验收跨瘤种分类。已有前列腺病例也不能擅自当无瘤阴性。
5. 运行记录包含命令、环境、代码/权重/tokenizer/输入哈希、候选查询、完整层数、逆映射、wall time、进程树 peak RSS 采样方法和单位、退出原因；轮廓栅格化核验后才报告探索性 Dice/体积与 overlay。试跑失败保留日志，不接入工作站、不修改原研究产物。

**继续和停止：** 权限/许可未解决、CPU 依赖无法闭合、权重键不匹配、空间还原不成立或资源触限，均停止该候选的当前试跑。运行成功后仍须单独完成 R3：核查训练重叠与患者级标签，冻结多瘤种/阴性/OOD 病例和类别选择/拒绝规则，再评估自动定位、分割和类型绑定。单例结果不用于调整后再自称独立验证。若没有可复核的类别决策机制或适合验证数据，结论为“分割组件可用，类型识别尚未解决”，不得进入 R4 自动瘤种功能集成。

### 独立复验与研究准备 Goal（2026-09-08，进行中）

用户已同意经两个子代理审查的三线计划并要求开启 Goal。A 复验已实现 E0–E5、修复范围内实证缺陷；B/C 推进自动定位分割及瘤种识别研究准备。新增依赖、权重获取与模型作业仍需具体授权；本轮不把 Goal 当作安装或推理授权。

- 新证据目录：`Annotation_Projects/reaccept-20260908-130954/`。`baseline.json` 固定当前 HEAD、源码与环境声明文件哈希。复用既有 16 项验收矩阵，只为实际覆盖缺口新增测试。原始影像只读，测试工程和故障注入使用独立文件；旧日志/JSON 不覆盖。
- 本轮数据无关层 1342/1342、全套 1467/1467，均退出 0；真实 MRI 三序列三面编辑/保存重开/Ctrl+Z 21/21，参考 overlay/实际候选 Save→磁盘恢复 6/6，均退出 0。MRI 两个交互脚本复制到本轮 `mri/`，仅修改 ROOT 定位并将 OUT 隔离，改动及原脚本哈希记录于 `mri-isolation.json`。VS 真实候选复用原记录，用于重新验证保存恢复，不冒充本轮重跑配准。
- 修复后按影响范围做定向回归，在最终稳定源码上完成必要全套验证。实际配准方向、旧 CT 能力守卫、参考层对应与候选保存按既有边界验收；未受影响的已有配准计算可复用经哈希检查的证据，不重复昂贵计算。
- A 测试与研究资料核查可并行；模型性能测量必须与工程测试错开。当前无产品源码修改，后续每个新证据均记录运行范围、命令、退出码、源码及产物身份。
- B/C 共用阶段门：R2 仅证明一例完整输入的运行/空间/资源可行性；R3 必须具备冻结的患者划分、类别决策及拒绝规则、阴性/OOD 和联合病灶指标；R4 才能判断接入。分割组件通过不代表类型识别完成。已有 VS 单例不作跨类别独立测试，前列腺病例不作已知阴性。
- R2 待授权作业须冻结配置与完整候选查询清单；15 分钟包含权重加载及全部查询，限一次模型作业。失败先只读诊断；追加推理必须说明原因、变更和预算，不能按类别拆作业或不断重试绕过上限。12 GiB 进程树采样阈值与新增下载总量 8 GB 仍为待批准值。没有权重访问/依赖授权时继续完成独立工程验收与研究准备，不将未知结果标成 PASS。

断点：本轮 A 复验已完成，无新增产品缺陷或产品代码改动。`checks.json` 记录上述四次运行、日志/报告哈希及 lint/diff 的退出 0；28 项本轮基线源码/环境声明零漂移，旧 MRI 38 项证据零不匹配。两张新截图已目视检查，坐标正确性的依据仍为独立 LPS 计算与数据断言。测试包括合成失败/过期回调、真实 CT 和 MRI 操作，不能外推为全格式或临床验证。工作区仍未提交。B/C 的下一执行门为具体试跑授权与官方受限权重访问；R3 的类别决策机制、独立患者多类型/阴性/OOD 数据及预注册阈值仍未具备，不能用本次工程 PASS 替代。Goal 保留进行中，不把准备完成标成肿瘤功能完成。

### R2 授权后准备（2026-09-08）

用户明确回复“同意”，批准独立环境、新增下载合计最多 8 GB、一次 CPU 模型作业最多 15 分钟（含加载及全部查询）、4 threads、12 GiB 进程树采样停止阈值。此前“待批准”记录是历史状态；本次不含代用户接受联系信息共享、GPU/云端、训练或额外推理作业。

本次输出集中 `Annotation_Projects/r2-biomedparse-20260908/`，以现有 Python 3.10 创建不继承 site-packages 的 venv，未升级 `dicom_gui`。首先安装独立访问客户端以兼容本机 SOCKS 代理；原环境访问检查因缺 socksio 报 ImportError，不能把它当作权重拒绝。随后独立环境使用已有本地凭据做 HEAD，返回 403/GatedRepoError，见 `weight-access-authenticated.json`；仅记录凭据是否存在，不记录凭据值。官方访问手续仍需用户完成。

源码 zip 探测在 20,000,000 字节上限触发 curl 退出 56，保留部分文件及计入下载预算；改为从固定提交获取 64 个必要源码/配置/许可文件，共 446,806 字节，全部 Git blob 摘要匹配，见 `source-acquisition.json`。这只是源码获取成功，不是 CPU 模型已验证。CPU 核心依赖安装独立记录于 `cpu-install.log / cpu-install.json`；Detectron2 编译及完整导入尚待验证，权重未下载、模型作业尚未消耗。

R2 环境实测补记：CPU 核心依赖安装退出 0；Detectron2 固定 `a2f4a8771ab77e8411c26b27f24f9489a28a2453`，源码包 1,508,403 字节。首次编译退出 1：本机标准库针对 PyTorch 2.6 `strong_type.h` 的 `std::is_arithmetic` 特化报 `invalid-specialization`。保留失败日志后，仅以 `CXXFLAGS=-Wno-error=invalid-specialization` 降低该诊断级别，`MAX_JOBS=2 / FORCE_CUDA=0` 重编译成功，未修改候选模型或算子源码。新轮子构建摘要 `98cc4279978989395e9e888697a2b0701abeaa947e308689158ebcdb76181bc0`（来自 pip 构建日志；临时轮子缓存不作为长期保留产物）。第二次安装日志独立保存，不覆盖第一次失败。

`check_cpu_imports.py` 离线导入 torch、torchvision、Detectron2 原生扩展及选定 FPN/语言编码等 10 项，全部通过，见 `cpu-imports.json`；`pip check` 退出 0，版本存 `environment-freeze.txt`。未构造模型，未加载权重，未执行推理，授权的一次作业尚未使用。访问探针时使用 hub 1.11；随后为 transformers 4.40 的依赖约束，独立环境解析为 hub 0.36.2，版本变化已记录，不能把早期访问探针环境与最终模型环境混称。`download-budget.json` 使用 pip 四舍五入下载尺寸加元数据/构建预留作保守预算，不宣称精确网络字节。当前真实阻碍仍为官方账号权重权限；用户已获提示自行处理，不再要求重复批准同一预算。

R2 输入准备补记：`prepare_input.py` 在现有 `dicom_gui` 只读载入 VS-SEG-001，输出独立 `input.npz`（仅 float32 imgs，不含参考标签、pickle）及来源 JSON。T1 完整 120×512×512，MR 0.5/99.5 percentile 实测为 1/849，裁剪后线性缩放 0–255；原始文件哈希不变，LPS→来源坐标往返最大误差 1.1368683772161603e-13 voxel。该序列角色是技术探针的明确选择，不宣称产品自动序列识别。

`check_preprocessing.py` 在独立环境调用固定源码的 process_input/process_output，完整输入有限；本例 512 方阵标记逆映射与非方阵 axis=1 的合成标记均逐体素一致，退出 0，记录于 `preprocessing-checks.json`。两组都不包含实际降采样，不能外推任意缩放时标签可无损恢复。官方原空间 TV 的 14 条轮廓、1093 点经独立 affine 校验，UID 一致、全部在来源范围内、各轮廓单层平面成立，距整数层最大误差 1.5894571632202315e-06 voxel，见 `reference-coordinate-checks.json`；尚未栅格化参考 mask 或报告 Dice。未构造模型、未使用一次推理额度。权重访问仍等待用户完成官方手续。

R2 权限更新：用户告知“好了”后，认证 HEAD 从 403 变为 302，官方固定权重 revision 为 `e473e5b2b1a3f44649734afd3dc7cf1770aaa9e2`，长度 4,460,902,829 字节，SHA256 `6ea0bee43b983a7490e0b48689add96440c4405ca4b50b9f2fe21d5d03fd9440`。仅接受完整下载且摘要一致的文件，正在下载不等于已验证。tokenizer 固定 revision `3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`，5 个必要文件共 1,392,152 字节，离线分词 6×77 通过。

`probe-protocol.json` 在模型运行前冻结 6 个查询，区分 README 列出的神经肿瘤/VS/卒中标签与尚未验证的 glioma/meningioma 自由文本查询；结果分别保留，无类别赢家，不伪造自主类型预测。独立 worker 使用安全 torch.load(weights_only=True,mmap=True)，键/shape 全匹配后严格加载；不遇到失败就放宽加载限制。`guard_probe.py` 监控整个模型进程组，900 秒/12 GiB 超限终止；无模型 timeout known-bad 已证实可结束非零退出的睡眠进程。该自测不是模型作业。实际模型作业只能在权重摘要通过后创建一次新的 `probe-001/`，不能覆盖或静默重试。

R2 首次作业实测：权重完整 4,460,902,829 字节且 SHA256 与官方一致，见 `weight-download.json`，下载退出 0。随后 `probe-001/run.json` 记录首次受限作业退出 1，1.3663176670088433 秒，Apple M4/32 GiB、4 threads，进程组采样峰值 203,456,512 字节；这些只属于配置阶段，不能当作模型速度或峰值内存。失败发生在自编 runner 向 Hydra struct 配置直接写入 `local_files_only`；未构造模型、未加载权重、未推理。该问题是 runner 的配置适配错误，不是 BiomedParse 分割失败。

保留原 worker 副本与全部日志；修复为仅在 tokenizer 配置上使用 `OmegaConf.open_dict` 新增本地加载字段。`config-fix-checks.json` 已复现原 ConfigAttributeError，并验证修复后从同一 Hydra 配置成功离线实例化 tokenizer，不构造整个模型。原作业已占用获准的单次作业，真实推理次数为 0；按约定不自行重试。建议追加一次同配置/同预算重试，输出新 `probe-002/`，无新增权重下载；追加授权前不运行。guard 新增受限 run-id 参数且拒绝覆盖已有目录。原权重/查询/模型配置和资源上限不改变。

R2 第二次作业：用户明确“继续”批准重试，`probe-002/` 退出 1，3.7993284999975003 秒、进程组采样峰值 1,955,332,096 字节（同 M4/32 GiB、4 threads）。成功构造模型且 torch.load(weights_only=True,mmap=True) 安全读取 checkpoint；尚未将权重赋给模型或执行 forward。参数核对无 missing、无 shape error，仅多出 `loss_function.cls_loss_fn.pos_weight` 与 `loss_function.loss_fn.dice_loss.class_weight`。固定源码 `src/losses/biomedparse_loss.py:143` 与 `medsam_loss.py:126` 分别确认为 BCE/Dice 的训练损失 buffer，当前 BiomedParseModel 的 eval 路径不持有或调用 loss_function。

已保留第二次原 worker 并新增精确 `checkpoint_contract.py`：仅排除上述两个且不属于 expected 模型键的 buffer；其余未知键或缺失键继续拒绝，推理张量 shape 检查及 strict=True 加载不变。不使用通配前缀、不改模型参数值。合成 contract 检查验证精确排除、对象不变、未知/缺失拒绝，记录 `checkpoint-contract-checks.json`。这是从实物 checkpoint 核实后的加载适配，不代表已完成实际模型加载或推理。两次获准作业已执行，实际 forward 次数仍为 0；下一次 `probe-003` 须取得追加授权，建议保持同资源上限且不重新下载。

### R2 单例实测结论与 R3 准入（2026-09-08）

用户第三次明确“继续”授权后，`probe-003` 完成安全 checkpoint 读取、精确排除已证实训练 buffer、其余权重 strict=True 加载及完整 120 层/6 查询 CPU forward，退出 0。原配置/权重/输入/查询不变，无额外模型作业。`probe-003/run.json` 固定代码适配文件、环境、输入、权重和输出摘要；Apple M4、macOS 26.5.2 arm64、32 GiB、torch 2.6.0、4 threads、slice batch=1，总 wall time **488.4870780420024 秒**，每 0.25 秒采样的进程组 RSS 峰值 **5,204,688,896 字节**，低于 900 秒/12 GiB 上限。采样不是无超调硬内存隔离；这些数值只属于该权重和本次完整作业，不推广为所有病例速度。

独立后处理：`evaluate_probe.py` 在模型作业结束后读取官方 T1 原空间 TV 轮廓，按来源体素中心 even-odd 规则填充且包含边界，不做层间插值；14 条轮廓各占独立切片，无需猜测同层孔洞语义。正反绕序方形已知样例验证栅格化规则。参考 mask 共 13,627 voxel。`probe-003/evaluation/metrics.json` 记录探索性 Dice：brain tumor **0.6964168074929109**；VS intra-/extra-meatal 合并 **0.15602394612122725**；stroke lesion **0.2811202116058377**；glioma **0.029227557411273485**；meningioma **0.06614950634696756**。全部查询均有非空输出，多个不同查询与同一参考肿瘤重叠，不能按“有响应”认定类型，也不能用看过参考答案后的 Dice 排名作为自动类别选择。轮廓只是原空间官方参考的明确栅格化，不声称与其他分割软件的边界体素规则完全相同。

`overlay.png` 选择参考面积最大的第 31 层（选片不看预测），绿色为参考、红色为查询响应；已目视检查。视觉对照只辅助解释全卷数值，单张图不证明全卷或分类正确。VS-SEG 单例未验证训练排除，不是患者独立外部验证；glioma/meningioma 文本是本探针明确未验证的自由查询，失败不能扩大为模型对所有受支持条件都无效。

**阶段判断：** R2 技术可行性探针完成；本机可以在获准资源内完成此配置的整例文本条件分割。当前方案不满足自动瘤种识别与 R4 接入条件，不接入产品、不把类别字符串写成患者诊断。R3 正式验证仍为 **NO-GO**：缺冻结的可复核类别决策/拒绝机制、训练来源隔离证据，以及患者级多瘤种/阴性/OOD 参考清单和预注册联合门槛。下一步针对这些具体缺口选择已有候选中的分类组合或补证，不继续无界换 prompt/重复单例试跑。需要新训练、模型作业或研究范围变更时单独明确成本和授权。

本轮 Goal 的工程复验及肿瘤研究准备交付范围已达到：A 新回归及真实 CT/MRI 交互完成，B/C 从文档候选推进到实际 CPU 输出，R2 与 R3 准入结论都有证据。**不等于原始“自动分割并识别任意瘤种”功能已实现**。前三次作业与两次失败适配均保留；累计实测 forward 为 1 次。无需为本轮结案重复工程全套或模型作业。最终源码/证据一致性以本目录 `goal-completion-audit.json` 为准；整个工作区仍未提交，无 push 或远端 CI 声明。

### R3 分类组件补证（2026-09-08，R2 之后的只读核查）

本轮只查询公开论文、仓库和资料页面并更新本计划；没有下载新模型、安装依赖、训练或追加推理。查询范围是已有分类路线的补证，不宣称找遍所有模型。

- **BRISC 官方证据**：[固定论文 v5](https://arxiv.org/html/2506.14318v5) 的 Code Availability 指向官方 Kaggle 数据页面。论文明确原始来源缺患者/序列身份，不能保证患者独立划分；2D 图片文件名还编码类别。它可用于初步开发，不可单独承担整例 MRI 的患者独立验收。输入须使用匿名无标签文件名，类别与参考 mask 单独保管。官方 Kaggle 页本次未返回可读文件清单，因此官方预训练权重仍是“未核实”，不能写成不存在。
- **第三方 BRISC 组合**：[课程项目固定提交](https://github.com/Adib-Ishraq/BRISC-2025-Brain-Tumor-MRI-Segmentation-and-Classification/tree/af90d7e32f3c3eb67a24e866c5da5d4fd76495f4) README 提供 U-Net 分割、冻结 encoder 分类及联合训练路线。GitHub 完整递归树 `truncated=false` 未列出 checkpoint，Release 列表为空；README 使用训练后生成的本地 `.pth`，没有现成权重下载链接。该仓库不是 BRISC 作者官方代码；目前只算实现参考，不能作为现成分类器准入，也不能从代码 MIT 许可推断未知权重许可。
- **EfficientNetB1 + U-Net**：[原论文 v2](https://arxiv.org/html/2304.10039v2) 支持“分类与分割分别建模”的方法路线。本次正文和定向搜索未找到可核实的作者 checkpoint。仅保留方法参考，不因论文报告准确率而安排模型作业；搜索未命中不证明全球不存在。

**推荐与执行顺序：** 保留 BiomedParse 为分割研究组件，分类候选单独通过以下门槛后才考虑组合。不能以查询名称、非空响应、最大未校准响应或看过参考后的 Dice 选瘤种。

1. 先补候选实物：可定位的训练后权重及版本/摘要、权重许可、完整输入预处理、类别索引、训练来源。任一项缺失，标为待补证，不安装、不安排 CPU 作业；目前上述分类路线没有通过此门。
2. 再补验证病例：患者身份可追溯、类型参考来源明确，支持的各类型、已知阴性与范围外样例分开。开发/校准/测试按患者划分，训练重叠不明必须披露；不能用图像去重代替患者独立，也不能默认其他部位病例是阴性。
3. 候选与数据都具备后，冻结整例/病灶级类别绑定、拒绝规则和联合指标，再拟定一次有资源上限的 CPU 探针。输出必须区分支持类型预测、未能确定类型和不支持输入；具体阈值在独立校准集确定后冻结，不能在测试集上挑选。
4. 停止条件：本轮已完成一轮论文→官方入口→可见代码/Release 核查。缺实物的路线停止投入运行预算；只有新增具体权重或来源证据才重开，避免无界换搜索词和 prompt。若最终需要自行训练，先提交有数据划分、算力成本和验证边界的范围变更方案，不自行启动。

断点：本轮排除了“这个第三方仓库可以直接补齐分类”的假设，并确认 BRISC 的患者级证据限制。R3 仍 NO-GO，不能据此断言瘤种识别技术不可实现。下一项明确待办是核实官方 BRISC 文件清单及其是否含训练后权重；在证据未获得前不以第三方代码替代官方产物。产品代码、既有模型输出和测试证据未修改；工作区仍未提交。

### 固定模型交付路线 Goal 计划（2026-09-08，已确认需求后的下一阶段）

**目标：** 交付一份可执行的固定模型接入方案，明确能自动定位、分割、预测类型的候选组合及支持范围；若现成组合不满足条件，则交付开发方训练定版的备选成本方案。最终用户不训练、不需要先告诉软件瘤种。此 Goal 是选型与验证方案收敛，不冒充肿瘤功能已经实现。

| 顺序 | 工作与范围 | 验收产物 |
|---|---|---|
| G1 需求与状态核对 | 沿用工程验收与 R2 证据，确认用户无需训练；不把 CPU 单例通过扩成分类通过 | 本节与当前结论同步，旧成果不重复执行 |
| G2 现成模型补证 | 先核实 BRISC 官方文件清单；随后只补已有候选中的关键缺口，必要时最多补充 2 个有具体权重入口的新候选 | 每项记录官方来源、版本、权重可获得性、独立权重许可、训练来源、输入/类别映射；缺项明确标注 |
| G3 软件适配评估 | 对证据最充分的一项检查整例输入、空间还原、病灶与类别对应、多病灶/未知类型、CPU 环境、模型定版与获取方式 | 推荐组合和支持矩阵；分发/缓存校验/版本记录/离线推理/失败提示的实施清单，不先写产品代码 |
| G4 验证设计 | 选择患者级有类型参考的数据，区分开发、校准、测试及阴性/OOD，核查训练重叠；先拟门槛再测 | 完整定位＋分割＋分类评估协议、数据缺口、一次 CPU 作业的配置及预算提案；无参考不可标为验收可行 |
| G5 去留与备选 | 已有权重可用则给出接入实施顺序；否则评估开发方训练固定模型所需数据、算力、许可和维护 | 一项推荐结论、证据与风险、可执行下一步；需训练时只交付成本方案，不启动训练 |

**默认方案：** 本地固定模型或固定模型组合，用户加载影像后点击分析；自动处理支持范围内的输入，返回病灶范围及类型预测，不能确定类型时明确保留未知。结果沿用已有工程保存体系，拟记录模型版本、输入来源、类别与分割对应、参数、输出格式/位置。模型权重是否能随安装包提供须查实际许可；需要个人登录或单独同意条款的权重不能直接描述为无手续自动下载。首批支持范围由证据推荐，不把软件支持 CT/MRI 等同于模型支持所有部位与瘤种。

**界限与停止规则：** 本 Goal 可进行公开资料/代码只读核查、现有环境和证据检查及本计划更新。20 GB 数据额度不转作新增模型或依赖额度；此前 R2 作业次数已使用。新依赖、新模型作业、GPU/云端或训练必须先形成具体资源提案，不从“可以由我们训练”推导为具体作业授权。每候选完成官方论文→代码/模型页→文件/Release 一轮核查后归类；没有新证据不重试。页面不可访问记录为未知，不绕过访问控制。有限候选仍不能证明可用时，完成有理由的暂不接入结论与训练备选，而非无限搜索或宣称技术不可能。

**完成条件：** G1–G5 都有可审查产物且推荐与现有证据一致；允许结论为现成方案暂不满足，但必须说明精确缺口和下一步成本。文档完成、模型实测完成、软件接入完成分开报告。启动时 G1 完成；G2–G5 的后续完成与限制见下方“固定模型路线交付”。工作区未提交，不 push。

### 固定模型路线交付：G2–G5（2026-09-08）

#### G2：有限补证结果

本轮在既有 12 项基础上仅补 2 个有具体权重入口的分类项目（不是重新扩大到 12 项）。下列源码与元数据只读获取，未下载模型二进制或运行外部代码。支持证据集中 `Annotation_Projects/r3-fixed-model-20260908/`；`evidence-hashes.json` 固定文件摘要。

| 候选 | 本轮核实的实物与输入 | 处置与精确缺口 |
|---|---|---|
| BRISC 官方入口 | [Kaggle API](https://www.kaggle.com/api/v1/datasets/list/briscdataset/brisc2025) 完整分页 78 页，15,591 个唯一文件；10,793 JPG、4,793 PNG、5 个 README/manifest/hash 文件，总声明大小 276,583,891 bytes。查询时元数据版本 6、更新时间 2025-11-04；清单不含训练代码或 checkpoint | 这只证明该次可见数据发布清单没有成品权重，不证明作者其他入口不存在。与论文“代码在该入口”不一致，记录而不猜测。没有下载影像，清单数量不等同独立患者数或论文全量样本核验。结束此入口追查 |
| BRAINet / ThisenEkanayake | [HF 快照](https://huggingface.co/ThisenEkanayake/brain-tumor-detection/tree/005d14ba1c1b1cafe80698e64b0740e8c54e1016) 列 `multiclass-classification/multi_class_resnet.pth` 44,794,891 bytes，LFS 声明 SHA256 `9efb12bb238a8b068eeea54f334621bd16692d92f96c67a478acf6e20b0b5e52`，未下载故不称字节已验。模型卡声明 MIT；代码固定 `9ad329c41d14f897c1eca2449bc306642596697c`。ResNet18、RGB224²、ImageNet normalization、4类，代码 CPU fallback | 有可定位权重，但模型卡将四分类来源写为 BraTS2020；[BraTS 官方](https://www.med.upenn.edu/cbica/brats2020/data.html) 是 glioma 数据，不能据此解释另两种瘤。代码仅指向本地 ImageFolder，未闭合训练来源；每 epoch 查看 test 不能算封存外测。无病灶实例输出/整卷协议、患者排除或 OOD 验证。暂不接入；不为此来源矛盾运行一次模型就当解决 |
| Halemo CNN | [固定代码](https://github.com/HalemoGPA/BrainMRI-Tumor-Classifier-Pytorch/tree/51587638ce55eda26a240fea474dd8046f031c57) 完整树列 `models/model_38` 11,176,858 bytes，Git blob `d9be507da36a9d1491916fcc2f00c1c0ca2771f0`；不是模型 SHA256。仓库 MIT。RGB224²/ImageNet normalization，训练 notebook 指向 Kaggle brain-tumor-mri-dataset | notebook 用 `enumerate(list(set(self.labels)))` 建类别索引，权重保存仅 state_dict；没有固定训练映射证据。`src/model.py` 建 5 输出，`src/utils.py` 只对前4项 softmax，界面类别写死。不能证明显示标签与模型编号相符。暂不接入，不依据几个已知答案反推映射；需要原训练映射与输出契约证据。无3D病灶绑定和患者独立证据 |

HF 的许可声明是发布方元数据，不替代训练数据授权链审查。两项均无本机 CPU 实测，不能引用网页速度/准确率作为本项目指标。BRISC 数据与部分 Kaggle 分类来源存在重用风险；新分类器不能默认拿 BRISC/Figshare 当独立外测。候选数已达本阶段上限，停止扩展搜索。

#### G3：推荐架构、支持矩阵与改动范围

**当前推荐：暂不进入产品模型接入；保留“固定分割组件＋独立分类组件”作为后续开发结构，当前分类槽位未准入。** BiomedParse 有单例 CPU 证据，但不是通过多病种质量验收的成品；不把 BRAINet 或 Halemo 强行拼上就称功能完成。

| 范围 | 已有能力 | 模型交付承诺 |
|---|---|---|
| 工作站 CT/MRI 标注与工程存储 | 已实现并验收 | 维持已有格式/空间边界 |
| VS-SEG-001 的指定 T1 整卷 | BiomedParse 单例文本条件分割实测 | 仅技术证据，无瘤种识别承诺 |
| 脑 MRI Glioma/Meningioma/Pituitary | 分类标签语义存在，未闭合患者与整卷协议 | 推荐研究范围，不是已决定首批支持；不能给任意切片/病例自动下类型结论 |
| 其他部位、CT 肿瘤、其他瘤种或多发不同类型病灶 | 没有本轮通过的完整组合 | 不支持模型分析时明确解释，阅片/标注仍可用；不能默认为 No tumor |

**后续接入顺序（准入后才实施）：**

1. 固定模型清单：model ID/revision、代码和权重摘要、许可/附带声明、标签语义、模态/序列/空间/强度输入契约、适配器版本。符合再分发条件时随安装包提供；否则明确首次获取手续与大小。下载临时文件、摘要校验、原子移入缓存，断网/损坏不加载。用户不用安装训练工具、上传病例或训练；离线运行不再隐式获取依赖/权重。
2. 新增隔离推理适配模块，输入是来源绑定的整例体积与序列角色；输出是来源网格上的病灶实例与各实例类型状态。禁止把整张切片分类结果复制给每个病灶；若采用裁剪/多切片聚合，须由训练输入及校准协议证明其有效性，不能直接改现成模型的输入分布。固定接口允许以后替换模型而不重写保存与编辑体系。
3. 复用 `annotation_state.py:add_ai_result(..., kind='lesion')` 与 `adopt_ai_command`：原始结果只读、人工采用进入 Undo。`main.py` 现有 generation 守卫与 Qt 信号用于取消/过期拒绝；推理仍放后台。每病灶独立层/ID，不把 uint8 mask 当无限实例编号；实例过多必须受资源门限制。标量类别分数写 provenance，不伪造逐体素 confidence。
4. `project_store.py` 已持久化 provenance、lesion_id 与 type_prediction/type_status/type_result_version；先复用并增校验。结果新增模型版本、来源 revision、分割版本、类型来源和未知原因。人工修改沿用现有“已修改”状态，不冒充分类重新运行。仅确有不能兼容的字段再提出 schema 迁移，不无故大改存储。
5. `ui_builder.py`/相应交互入口增加分析状态、病灶结果列表、取消、模型可用性与失败说明；继续提示 `.miwproj` 保存位置和已有 CSV/NPZ 内容，空间导出另按真实格式支持，不承诺未实现 DICOM SEG。只对新适配器、结果绑定、保存迁移与受影响 UI 做必要回归；不重新实现已有编辑能力。

改动集中于模型管理、隔离适配器、结果校验和 UI；大风险是整卷到病灶的类型绑定及错误结果拒绝，其次是权重分发/CPU依赖，非 Undo 或单像素编辑。

#### G4：患者级验证协议与准入状态

这是可实施的验证协议提案，**不是已经具备病例的验收运行**。在任何输出生成前固定模型、病例 manifest、类别表、阈值版本、输入变换与参考来源；没有满足下列条件则不启动正式 R3。

- 数据选用：开发方训练备选优先审查 [Figshare v8 原始 MAT](https://figshare.com/articles/dataset/brain_tumor_dataset/1512427/8)，官方 README 含 PID、原始影像、mask，标签1=Meningioma/2=Glioma/3=Pituitary，且有采集说明。4个ZIP声明合计879,493,326 bytes；它是233患者的选定2D切片，缺完整连续体积/真实患者空间与阴性，不能借它完成整卷链。可作为患者划分的分类开发数据，不作为来源不明现成模型的独立测试。
- 整卷外部候选：UCSF-PDGM 用于病理确证 diffuse glioma（[作者论文](https://arxiv.org/abs/2109.00356)）；MENINGIOMA-SEG-CLASS 用于有 MRI/RTSTRUCT/诊断参考的 Meningioma（[官方集合](https://www.cancerimagingarchive.net/collection/meningioma-seg-class/)）；已有 VS 可作受支持列表之外的探索样例，训练排除未证实。Pituitary 整卷、已知无瘤同域 MRI、其他瘤种/OOD 以及跨类别共同采集域仍是缺口。本轮不下载或宣称已有清单；TCIA 两页抓取超时，集合线索不等于逐例准入。
- 防泄漏：患者及同一患者全部时间点只进一个划分；记录 site、sequence、类型来源、mask来源、授权与训练交集。模型输入去掉类别文件名/目录/参考；参考由评估脚本单独读取。不同瘤种分别来自不同机构时另设同机构多类型检验，否则只报告可能存在机构混杂，不能声称学到了病理区别。
- 开发阶段建议患者分层60/20/20划分（开发/校准/封存测试，固定 seed 20260908）；外部数据独立报告，不混回开发。每拟支持类别及阴性/OOD组先至少10患者做探索检查；不足只做可行性。正式样本量按目标误差和患者级置信区间另算，不把10例当可靠性保证。数据质量/划分核查可先做，正式阈值冻结必须在测试揭盲前完成。
- 自动路径：完整体积自动提出病灶；不能用参考mask或人工挑瘤切片定位。每个预测实例仅匹配一个参考实例，以最大总体 IoU 一对一匹配，IoU≥0.1 为探索检测匹配阈值；分裂产生的额外实例计 FP，合并造成未匹配参考计 FN，同时单列 split/merge。匹配阈值不是精细分割通过线。
- 指标与失败计数：检测 sensitivity/precision、FP/case；匹配病灶 Dice/HD95（真实 spacing、mm），漏检分割记 Dice0、HD95未定义并单报；阴性双空不加入病灶 Dice 均值。类型报告患者级及病灶级混淆矩阵、macro-F1、各类召回、拒绝率；未知拒绝不从总分母删除。联合成功要求同一病灶被匹配、Dice≥0.7且类型正确；0.7仅为本项目探索门槛提案，不是医学标准。患者 bootstrap 给95%区间，不能按相邻切片重采样伪扩大样本量。
- 拒绝校准：输入不合约直接 unsupported；未检出不等同确诊无瘤；类别不一致或低于校准门槛为 unknown。分类温度/阈值只在校准组确定，目标是在保留预测中错误率≤10%并保留≥80%的受支持样例；达不到则当前规则失败，不靠大量拒绝求高准确率。正式准入同时要求各支持类检测召回≥0.8、类型macro-F1≥0.8、联合成功率≥0.7、阴性FP/case≤0.5、OOD错误接受率≤0.1；均为待实际数据评估的科研原型门槛，不是临床效能承诺。数量不足或95%区间跨门槛时不宣称正式通过，保留探索结果。
- 技术门：来源/空间往返、版本绑定、缺序列/错误模态拒绝、损坏权重拒绝、取消/过期回调、保存恢复与未知状态均须通过。端到端空间错误零容忍，不能以分类分数抵消。新增 CPU 探针建议仅1整例、4 threads、15min/12GiB进程组采样，固定所有查询/变换，无隐式下载；仅在候选输入与来源问题解决且具体作业获准后运行。资源超限即止，不自动重试。

**G4 结论：协议已形成，参考数据与现成分类模型的来源隔离仍不满足正式运行条件。** 阈值是预先提出的开发目标，不是已获临床或统计充分性证明；首批支持范围与数据落实后冻结正式协议，不能看测试结果再降低门槛。

#### G5：去留决定与开发方训练成本备选

**本轮决定：暂停完整自动瘤种功能接入，不启动另一次现成分类器推理；优先保留已有模型资产，下一步如继续开发，先做患者级数据可用性清点，再决定开发方训练。** 用户不承担训练。若以后获得可核实训练来源/类别映射的现成权重，可重开相应候选；不需要推翻软件架构或按每个部位从零开发软件。

备选不是“训练一个JPEG分类器即可完成需求”：由开发方训练固定的病灶级分类器，复用分割器并对整卷域和病灶输入单独验证；若目标定位/分割本身未过门，不能仅补分类头。Figshare 可做小型方法原型，进入整卷产品验证前仍需同域连续MRI与每病灶标签。

| 阶段 | 有边界的成本提案（估算，非实测或报价） | 停止/交付 |
|---|---|---|
| 数据清点 | 约2–5个开发工作日；先只读manifest/病例角色、许可、PID与同域覆盖，公共数据下载仍按剩余20GB总额度核算 | 缺关键类别、阴性或同域整卷则先报告缺口，不开始训练 |
| 小型分类原型 | 数据门通过后约3–5个开发工作日；预训练2D encoder＋固定患者级聚合/病灶输入方案仅选一条，最多2配置 | 建议另批GPU探针最多1小时、总训练预算先封顶12 GPU小时、16GiB级设备；是预算上限非保证足够，不在本机CPU盲跑长训练 |
| 联合验证与适配 | 约5–10个开发工作日，前提是合格数据和权重已到位 | 冻结模型与阈值后评估，未过门保留失败，不发布为可用功能 |
| 软件打包与回归 | 约3–5个开发工作日，前提是联合门通过 | 模型清单、离线推理包、许可、结果版本、可恢复下载与用户无需训练的验收 |

这些是人工作业量估算，AI辅助速度、数据获取、标注时间和科研迭代不可预先保证；不相加承诺上线日期。租用成本按批准时单价 r×最多12小时另加存储/流量计算，本轮未选服务商也无价格报价。云端上传、GPU、训练、新依赖均未授权执行；若只允许当前CPU，先限时测吞吐，不能据已有分割速度估训练耗时。最终训练交付必须固定架构、权重/摘要、标签表、预处理/聚合/校准、训练划分、验证报告与许可；不要求最终用户保留训练数据或安装训练工具链。

**完成审计：** G1需求记录、G2四条补证处置、G3架构/支持矩阵/文件范围、G4数据选择与缺口/防泄漏/指标和资源协议、G5推荐与成本备选均已落在本节。证据明确支持“暂不接入”，不支持“自动类型功能已实现”。当前 Goal 的选型与方案交付完成；R3正式模型验证仍NO-GO，R4未启动。只修改计划并保存忽略目录中的公开资料证据，产品代码与已有测试/模型输出未改动，工作区未提交。

### 用户要求重新找方法：整例基础模型补查（2026-09-08）

用户在上一轮选型交付后明确要求“再想想方法，找找资料”，据此重新开放有针对性的资料核查，不受上一轮结束搜索结论限制；未授权新增模型作业或训练。**修订建议：先深入 Prima 的现成分类头，不先转入自行训练。** 之前停止的是已查候选，不能扩大成现成模型路线已穷尽。

- **Prima，新的优先候选。** [作者实验室](https://apps.mlins.org/) 与[官方代码固定提交](https://github.com/MLNeurosurg/Prima/tree/604f1fc4dd7059c278d4d34bbbcaab3e404fbcd4) 提供完整模型 `primafullmodel107.pt`（含heads）和 VQ-VAE tokenizer 的 Google Drive 入口。`end-to-end_inference_pipeline/README.md` 明确输入一次检查的多序列 DICOM 目录、输出 JSON。实际 `prospective_eval.json` 含成人 Glioma、高/低级别 Glioma、Meningioma、Lymphoma、脑转移瘤、Schwannoma，以及 Pituitary adenoma 等任务名；这些是代码任务清单，不冒充已下载 checkpoint 内标签核验。比单张JPEG分类更接近需求。
- CPU 适配有具体路线：pipeline 自动选择 CPU，`model_parts.py` 对 flash_attn 导入失败提供 `no_flash_attn_varlen_substitute` 和关闭 flash 的方法。不能只因 requirements 列 flash-attn 就淘汰；也不能因此宣称 CPU 已跑通。需继续检查 tokenizer、checkpoint安全加载、attention 内存与其他依赖闭包。代码 MIT；权重独立许可/大小/摘要与本机资源仍未核实。官方说明2026-02-19修正过 priority 模型，必须固定实际文件版本。
- 分类含义：`full_model.py` 返回各诊断 head 输出减去阈值，不是归一化概率或唯一赢家，不能标为“xx%确定”。[论文 v1](https://arxiv.org/html/2509.18638v1) 基于整次检查与报告监督，疾病标签不等于每例病理金标准；与后续论文版本的指标不混用。本轮不引用平均AUC作项目性能。病史/检查描述可能含诊断，验证必须区分纯影像与临床上下文，不能把已知瘤种塞入文本。
- **推荐组合假设：Prima 整例疾病预测＋BiomedParse 的定位分割，两个组件均用固定发布权重。** 软件可自动生成模型查询，用户无需指定瘤种。先独立保留类别结果和空间结果，验证同一病灶绑定后才合并；不能先按分类选择唯一分割目标，再把非空结果当分类得到独立验证。LIME只能作解释，不能当精确mask；多病灶或多类型冲突尤其不能把整例标签复制给每个病灶。该组合尚未实测，不宣称无需训练即可完成所有情况，但值得优先验证而不是先训练。
- **Brainfound 次级线索。** [gingerbread000/Brainfound](https://github.com/gingerbread000/Brainfound) 有图文预训练、zero-shot与报告代码；可见 segmentation 目录说明聚焦脑出血/中线移位，不足以证明跨瘤种精确分割。论文检索列出 Zenodo 18976379 权重存档，但页面本次工具报不可安全打开，PMC正文遇验证码，均未绕过；权重文件与许可保持未知。不要与另一个同名 BrainFound/DINO 项目混淆。

下一安全步骤：固定 Prima 权重元数据及分发条件→静态核实完整 CPU/安全加载输入链→形成同一例多序列MRI的有界试跑提案→再验证病例级分类及与mask绑定。若资源或权重许可实际不满足，再比较其他基础模型或开发方训练；本轮没有安装依赖、下载权重、上传病例或执行推理。上一轮G2–G5的历史交付仍保留，本补记替代其“下一步优先数据清点准备训练”的推荐排序，产品准入仍未通过。

### 纠正与替代记录

- “仅 Axial 编辑”“MRI 只留在研究范围”已被用户后续确认替代：工程包含 CT/MRI 和三视图编辑。
- “Undo 仅当前会话有效”已被用户替代：最近历史随工程保存。
- 脑部 MRI 优先不是已确认需求；先比较候选，不因 Glioma 示例锁死全项目范围。
- 不预设每个部位重新训练；先查统一模型与现成组合。
- 不把目标名称、肿瘤子区域或器官部位标签当成自主识别瘤种的证据。
- 用户要求默认合理选择并连续推进；不再用频繁的小问题或每步等待“继续”代替执行。
- 2026-09-07 审计修订：P1 部分载入不缩减完整工程；P2 旧缓存只迁工作结果、原始 AI 不可用；P2 模块/架构/测试清单同阶段同步；P3 性能运行须有机器配置和 JSON 证据。四项在计划层面已补齐，功能实现及行为验收仍未开始。
- 2026-09-07 第二轮：规范轴补来源/空间恢复契约、笔画导航冻结；需求轴补损坏历史恢复模式及 AI/配准结果自动保存。重合的来源绑定问题只计一次。其余加载隔离、能力分离、性能与研究验收前置属于实施清单补充；“计划可启动 E0”不等于 MRI/模型已验证，也不等于后续不会出现实现缺陷。
- 修订后两轴定向复核：上述发现的规则与验收已覆盖，未发现本轮指定范围内仍未解决的具体矛盾。此状态不代表穷尽审计或新功能测试通过；E0 及后续实测仍是阶段准入依据。

### Prima 试跑授权后的预检（2026-09-08）

用户明确“试一下吧”，开始准备一次Prima CPU试跑；默认沿用4 threads、15分钟、12GiB采样上限，下载大小须先核实。官方两项Google Drive权重链接在网页工具均返回 `not safe to open (non-retryable error)`，未改用其他通道绕过。此为工具访问受阻，不是已证明文件失效或模型不可运行。当前没有安装依赖、下载模型或执行forward，作业次数0。

已取得固定代码的入口/配置/下载脚本与实际加载器，见 `Annotation_Projects/r2-prima-20260908/source-preflight.json`。发现完整checkpoint入口显式使用 `weights_only=False` 与自定义pickle兼容映射；后续需先检查实物序列化内容和固定代码类，不能照搬无约束加载。现有VS同检查T1/T2可作技术输入候选，前列腺不能用于脑部模型。下一步需用户从官方链接取得两项权重并放入该目录，随后核对大小/哈希/许可及安全加载方式，继续独立环境和有界试跑；不把预检当模型失败或运行成功。

### 存储约束后的精简路线核查（2026-09-08）

用户截图显示 Prima fullmodel107.pt 为32G、tokenizer约126M，用户明确没有存储位置，随后同意查精简权重或更轻组合。暂停32G下载，不删除数据，不把此截图当运行内存实测。此前“请用户下载完整权重”已被本决定替代。

Prima 固定 `604f1fc4dd7059c278d4d34bbbcaab3e404fbcd4`，官方 releases 查询为空。`sample_prima_config_components.json` 确实支持 CLIP+heads 分开加载，但只列本地占位路径；已查README/实验室下载页仍只链接完整模型和tokenizer。未找到可直接下载的官方轻量/量化权重，不证明其他地方不存在。分类头依赖影像编码器，不能只下载head完成影像推理；没有检查32G实物，不声称它大部分是可删训练状态。

新增更轻路线：同实验室 [NeuroVFM](https://github.com/MLNeurosurg/neurovfm)，代码固定 `9240021d4ef5c262b21cee5d219c2adf65f4d42f`。HF元数据：`mlinslab/neurovfm-encoder` revision `d5194fc70a162185f8ef062e362bd522a35312a9`，pytorch_model.bin 286,576,042 bytes；`mlinslab/neurovfm-dx-mri` revision `628b661744482e528374d9c9ef1b54aded3d4c6e`，3,789,726 bytes；权重合计290,365,768 bytes，未下载或字节校验，非运行内存。仅编码器+诊断头可组成分类路径，不需要报告LLM或外部reasoning API。均为manual gated，模型许可声明CC-BY-NC-SA4，官方要求机构邮箱申请；本轮未代提交。输出仍是study-level类型判断，不是精确分割或病灶级绑定。

CPU细查：encoder调用已传use_flash_attn=False，但vit.py仍顶层导入FlashAttention/PatchEmbed/FusedMLP，部分类构造要求FusedDense，cross-attention仍调用flash函数。不能靠关单一开关就宣称CPU可用；tests中部分CPU测试使用替身，不证明真实权重CPU推理。优先下一步做固定源码的CPU等价替换范围审计（Linear、norm、attention、参数键和数值一致性），再决定有无必要申请权重。若需重构模型或无法证明等价，报告成本，不静默更改模型求通过。当前未安装依赖、下载权重、推理、训练、上传或清理磁盘。

### NeuroVFM CPU适配范围审计（2026-09-08）

用户同意后完成固定源码检查与小型合成运算检查；14项模型/管线Python源码副本及摘要在 `Annotation_Projects/neurovfm-cpu-audit-20260908/`，未导入整个外部项目、未下载权重、未装依赖、未运行病例。使用既有dicom_gui torch2.11.0，检查仅2 threads。

结论：存在有边界的CPU适配路线，值得保留；尚未证明完整模型等价或实际可运行。核心范围为FusedDense→保持weight/bias名称的Linear，FusedMLP→fc1/GELU(tanh近似)/fc2，以及保留FP32 residual、eps、prenorm返回语义的LayerNorm/RMSNorm；不能默认nn.GELU()，上游FlashAttention v2.6.3 FusedMLP默认gelu_approx。顶层flash/PatchEmbed导入需解耦；MIL分类池也依赖FusedDense。CrossAttention、完整分词/位置编码和具体权重配置须继续按实际调用确认，不能删去未理解分支。

已测：从固定vit.py AST提取原SelfAttention/pad/unpad，仅以Linear替代FusedDense构造，在两条长度3和5的随机序列上比较独立逐序列PyTorch SDPA，float64最大绝对误差5.551115123125783e-17；去掉padding屏蔽的known-bad误差0.13174734138530153，被同一检查发现。见check_attention.py/attention-check.json。上游layer_norm_ref与手写eval模式残差加和/归一化公式比较，float32误差4.76837158203125e-07；错误地归一化后再加residual误差3.7653937339782715，见norm-check.json与上游源码副本。这些是算子公式检查，不是与GPU kernel对照、预训练权重加载或整例性能测试；未声称MLP已做数值核验。

同时发现接入守卫：官方diagnostic loader使用strict=False，正式适配须逐项验证missing/unexpected/shape；标签表通过路径是否含mri/ct选择，隔离目录不能隐式决定类别表，应显式绑定MRI标签和模型revision；标量sigmoid分数非已校准准确率。普通attention会显式生成N×N矩阵，290MB权重不保证小内存；完整试跑前统计token数，按实际batch/head/dtype预算峰值，不为省内存静默丢切片。

下一步是实现独立CPU适配原型并检查完整随机配置/键结构，再以获准权重做strict加载和病例试跑；访问许可仍需用户在官方HF页面办理，且需要先确认实际配置与MRI类别表。不能直接把当前公式检查当权重准入完成。产品源码未改，旧工程测试和模型输出未改，工作区未提交。

### NeuroVFM独立CPU原型（2026-09-08）

用户“继续”后在同一忽略目录实现cpu_prototype.py，显式AST载入固定官方类，在独立namespace替换Linear、tanh近似GELU双层MLP、eval残差norm与MIL分段max/sum；不创建伪造flash_attn安装包，不修改上游源码副本或产品。两层小型随机VisionTransformer（linear embedding、无位置编码）接3类MIL分类头实际CPU运行退出0；两序列packed vs单独运行features误差4.76837158203125e-07，logits误差4.656612873077393e-10。参数键/shape清单在prototype-result.json；同构strict恢复通过，故意缺键被拒绝。并未证明与官方checkpoint键一致。

首次随机配置未给MLP hidden_dims而失败，随后明确为[8]；移除flash导入后PatchEmbed类型未定义，显式加载仓库本地PatchEmbed解决。失败原因与修复记录于prototype-history.json。这些仅为原型联调，不是预训练模型作业。该原型不支持训练；没有验证完整发布配置的位置/voxel嵌入、cross attention、GPU kernel数值差异、真实DICOM输入或整例性能，不能称模型CPU适配完成。

为进入发布配置验证，本次仅请求两项固定revision的config.json，HF均返回401（匿名访问），见config-access.json；不能推断用户已登录账号也无权限。需要用户在官方encoder与dx-mri页面完成访问批准。建议现在申请约290MB组合的访问；只申请不代表已下载、批准或运行。取得配置后继续对应架构原型，再严格检查权重，最后做有界MRI试跑。无新依赖、GPU/云端、上传、权重下载或真实病例推理；工作区未提交。

NeuroVFM访问复查：用户告知“做了”后，使用现有独立环境及本机HF凭据读取两个固定revision的config.json，两项均返回403/GatedRepoError，见neurovfm-cpu-audit-20260908/authenticated-config-access.json。当前只能确认本机凭据尚不能读取，不能直接认定用户没有申请或一定尚未审批；也可能浏览器申请账号与本机凭据不同。未下载权重、未启动模型。下一步待批准或对齐账号后重查，不重复提交申请，不索取聊天中的token。

### R2 纯文字资料复核（2026-09-22，MUI 恢复后的有界桌面研究）

本机 `/Users/sc/01_Projects/GUI` 已丢失，2026-09-08 的 `Annotation_Projects/r2-*`、`neurovfm-cpu-audit-20260908/` 等独立研究目录（含已下载的 BiomedParse v2 权重、NeuroVFM CPU 原型代码摘要）均未随本次恢复带回，见 `docs/RECOVERY_20260921.md`。用户明确本轮"只做纯文字/公开资料研究"：不下载模型、不装依赖、不跑代码、不做任何需要本机凭据的鉴权请求（包括上面 NeuroVFM 的 HF gated-repo 复查，那需要本机凭据发起认证请求，本轮不重复）。只用 WebFetch/WebSearch 读取论文与仓库公开页面。

- **Prima 论文已有 v2（2025-12-16），此前的引用只查过 v1。** [论文 v2](https://arxiv.org/html/2509.18638v2) 明确写"The Prima model parameters will be publicly available for investigational use only under an MIT license"——权重与代码都是 MIT、仅限研究用途；这更新了 2026-09-08 记录里"权重独立许可…仍未核实"的说法，现在论文正文本身给出了权重许可声明（仍是论文自述，不等于本机已核实实际分发文件的许可文本一致）。训练/测试划分是同一医疗系统内的时间隔离（训练止于 2023-05-31，测试为 2023-06-01–2024-05-30，29,435 名患者），不是跨机构的患者级独立验证，也没有说明同一患者是否可能跨越两个时间窗；未讨论 OOD/拒绝机制；输出是 52 诊断标签的 study-level 多标签向量（multi-hot，positive-weighted BCE 训练），不含病灶级定位，仅能事后用 LIME 解释——与本文件 2026-09-08 的既有提醒（"LIME 只能作解释，不能当精确 mask"）一致，不需要修改那条结论。**净结论：Prima 的权重可获得性证据比此前更明确，但患者级独立验证证据仍不满足 R3 门槛（同机构、非跨机构患者划分，且缺 OOD 拒绝），G2–G5 的推荐排序不变。**
- **EfficientNetB1+U-Net、BRISC 2025 两条分类线索原地复核，结论不变。** 重新读取 [EfficientNetB1 论文 v2 全文](https://arxiv.org/html/2304.10039v2)：确认是 2D 切片按 70/15/15 随机比例划分（不是患者级），未提供代码或权重下载地址，未讨论 OOD。重新读取 [BRISC 论文 v5 全文](https://arxiv.org/html/2506.14318v5)：确认原文写"complete subject-level independence cannot be guaranteed"，许可 CC BY 4.0，仍未提供官方预训练权重下载。定向搜索发现两个新的第三方仓库（[youldash/brisc-tumor-segmentation](https://github.com/youldash/brisc-tumor-segmentation)、[sagor5271/Brain-Tumor-Segmentation-on-BRISC2025-](https://github.com/sagor5271/Brain-Tumor-Segmentation-on-BRISC2025-)），均是社区训练的分割（非分类）模型，不是官方发布，且不解决"分类组件"这个具体缺口，不纳入候选池（候选池上限已在 R1 用满）。两条线索仍卡在"无可核实的现成分类权重"，与 2026-09-08 的结论一致。
- **不做的事，如实记录：** 未重新核实 NeuroVFM 的 HuggingFace gated-repo 访问状态（那需要本机凭据发起鉴权请求，超出本轮"纯文字研究"范围）；未下载 Prima 的任何权重文件来核实上述许可声明是否与实际分发文件一致；未新增候选、未触碰 `tumor_model_admission.py`。

下一步仍是 2026-09-08 记录里已经写清楚的那条：NeuroVFM 待用户对齐 HF 账号权限后再复查访问状态；Prima 若要继续，下一步是核实权重实际大小/摘要是否与许可声明一致，以及能否找到跨机构的独立患者级验证证据——这两步都需要下载文件或联系官方，不在本轮范围内。工作区仅改动本文档，未改产品代码，未提交模型作业。

### NeuroVFM 访问状态复查（2026-09-22，用户对齐账号权限后）

用户明确指示"账号权限对齐后再复查访问状态"。用本机既有 `huggingface_hub`（1.11.0）凭据（`whoami` 确认为账号 `sunce764`）对两个固定 revision 发起只读元数据请求：`hf_hub_download(repo_id, filename='config.json', revision=...)`，只取 config.json，不取权重文件（`pytorch_model.bin`）。

- **`mlinslab/neurovfm-encoder`@`d5194fc70a162185f8ef062e362bd522a35312a9`：访问已获批**，不再是 2026-09-08 记录的 403/GatedRepoError。取回 `config.json`（385 字节）：`{"which": "vit", "params": {"embed_dim": 768, "depth": 12, "num_heads": 12, "embed_layer_cf": {"which": "voxel", "params": {"in_chans": 1, "embed_dim": 738, "bias": true, "fused_bias_fc": true, "patch_hw_size": 16, "patch_d_size": 4}}, "pos_emb_cf": {"which": "pe3d", ...}}}`——ViT-Base 规模（12层/12头/768维），体素 patch 编码（16×16×4）+ 3D 位置编码；`fused_bias_fc: true` 印证了 2026-09-08 "NeuroVFM CPU适配范围审计"里对 FusedDense/FusedBias 的顾虑不是空想，实际配置确实要用到。
- **`mlinslab/neurovfm-dx-mri`@`628b661744482e528374d9c9ef1b54aded3d4c6e`：访问已获批**，同样不再 403。取回 `config.json`（212 字节）：`{"which": "classify_then_aggregate", "params": {"hidden_dim": 384, "W_out": 74, "mlp_out_dim": 74, "mlp_hidden_dims": [384], "use_gating": true, "use_norm": true, "use_output_bias_scale": true}}`——MIL 分类头输出 74 维（不是 Prima 的 52 维，两个模型的诊断标签体系不同，不能混用或直接比较）。
- **仍未下载**：`pytorch_model.bin` 权重本体（合计约 290MB，2026-09-08 已记录字节数但未下载校验）。本次只验证了"能不能读到配置"，不代表已验证权重文件本身的哈希、许可条款文本、或模型可以在 CPU 上正确加载与推理。

**结论：** 访问门已开，可以推进到"下载并校验权重哈希→按 2026-09-08 的 CPU 适配范围审计继续静态核对完整架构键→有界 CPU 冒烟"这条路径，但下载 290MB 权重文件、安装/核对推理所需依赖、执行任何前向计算，都超出当前"只读元数据"的授权范围，需要用户单独明确批准（对应硬边界"不下载模型、不训练、不用 GPU"）。产品代码未改，未安装新依赖，未下载权重文件，工作区本节只追加了这段记录。
