"""离线帮助内容与纯Python搜索；不访问或改变工作站状态。"""

TOPICS = {
    'window': {
        'title': ('窗宽窗位', 'Window width / level'),
        'intro': ('调整影像的明暗和对比度，观察不同强度范围内的细节。',
                  'Adjust brightness and contrast to inspect different intensity ranges.'),
        'steps': ('选择窗位预设，再按需调整窗宽 W 和窗位 L。窗宽控制显示范围，窗位控制范围中心。',
                  'Choose a preset, then adjust width W and level L. Width controls the displayed range; level controls its centre.'),
        'sections': (
            (('了解原理', 'Understand the principle'),
             ('原始强度 → 窗宽窗位映射 → 屏幕灰度\n\n调窗改变显示映射，不修改原始体素值。范围之外的强度会显示为端点灰度，因此某些细节可能暂时看不见。',
              'Original intensity → window mapping → screen grey\n\nWindowing changes the display mapping, not the original voxel values. Values outside the window appear at the end-point greys, which can hide detail.')),
            (('动手试试', 'Try it'),
             ('先打开一份演示 CT，记下当前切片、W 和 L。\n1. 固定切片，切换两个窗位预设。\n2. 观察哪些细节更容易看清。\n3. 想一想：画面变亮，原始体素值也变大了吗？\n4. 手动恢复开始时的 W 和 L。\n\n帮助不会替你加载数据或调整设置。',
              'Open a demonstration CT and note the slice, W and L.\n1. Keep the slice fixed and compare two presets.\n2. Observe which details become easier to see.\n3. Does a brighter display mean larger original voxel values?\n4. Manually restore the initial W and L.\n\nHelp does not load data or change settings for you.')),
            (('数据与测量说明', 'Data and measurement'),
             ('屏幕灰度、原始强度和 HU 不是同一个概念。HU 与毫米等单位是否可用，以当前影像的标定状态为准；帮助文字不代表当前数据已经标定。\n\nROI 用于统计区域内的原始强度。调窗不能补足缺失的强度或空间标定，也不能证明测量的临床有效性。',
              'Screen grey, original intensity and HU are different concepts. Availability of HU and physical units depends on the current calibration status; this page does not certify that calibration.\n\nROI statistics use original intensity. Windowing cannot supply missing intensity or spatial calibration, or establish clinical validity.')),
        ),
    },
    'recon': {
        'title': ('重建实验室', 'Reconstruction laboratory'),
        'intro': ('从不同角度的投影重建图像，观察重建方法与采样设置的影响。',
                  'Reconstruct images from projections and explore reconstruction methods and sampling.'),
        'steps': ('载入 Shepp–Logan 模体 → 生成弦图 → 选择 BP 或 FBP → 查看结果。练习使用内置模体，无需 AI 模型。',
                  'Load the Shepp–Logan phantom → generate a sinogram → choose BP or FBP → inspect the result. This exercise needs no AI model.'),
        'sections': (
            (('看懂这几个概念', 'Understand the concepts'),
             ('模体 → 不同角度的投影 → 弦图 Sinogram → 重建图像\n\n模体是已知的模拟对象。弦图将各个角度的投影排列成图；当前显示横轴是角度，纵轴是探测器位置。BP 将投影反投影回图像空间；FBP 在反投影前对投影进行滤波。',
              'Phantom → projections at different angles → sinogram → reconstructed image\n\nA phantom is a known simulated object. The displayed sinogram places angle horizontally and detector position vertically. BP back-projects the projections into image space; FBP filters the projections before back-projection.')),
            (('做一个对比实验', 'Try a comparison'),
             ('1. 载入模体，记录角度范围、采样密度和 FBP 滤波器。\n2. 生成弦图，运行 FBP 对比，观察 BP 与 FBP。\n3. 如要比较采样密度：先卸下再载入同一模体，以清除上一张重建结果；保持角度范围和滤波器不变，只调整采样密度，再生成弦图并重建。\n4. 比较边缘、条纹和细节，记录你的观察。\n\n这会由你手动更改重建现场；如需保留当前结果，请先自行记录。帮助不自动运行或恢复实验。',
              '1. Load the phantom; note angular range, sampling density and FBP filter.\n2. Generate a sinogram and run the FBP comparison to inspect BP and FBP.\n3. To compare sampling density, unload and reload the same phantom to clear the previous reconstruction. Keep angular range and filter fixed; change only density, then generate and reconstruct again.\n4. Compare edges, streaks and detail; record your observations.\n\nThese are manual changes to your reconstruction workspace. Record any current results you need first. Help does not run or restore experiments.')),
            (('参数与结果说明', 'Parameters and results'),
             ('角度范围决定覆盖哪些方向；采样密度决定在这个范围内取多少投影，二者不能混称。\n\n生成弦图时可能使用上一张重建结果作为输入，请检查 Radon 来源提示和弦图标题。模体实验与真实扫描存在差异，显示效果不能单独证明算法优劣或临床适用性。\n\n“保存标注工程”不等于保存重建实验的完整过程。复核时应另行记录来源、角度范围、采样密度、算法、滤波器和软件版本；本帮助不会生成实验记录。',
              'Angular range determines the covered directions; density determines how many projections sample that range. They are different controls.\n\nSinogram generation may use the previous reconstruction as input. Check the Radon source message and sinogram title. Phantom experiments differ from real acquisition; visual appearance alone does not establish algorithm superiority or clinical suitability.\n\nSaving an annotation project is not a complete reconstruction experiment record. Separately record source, angular range, density, algorithm, filter and software version. Help does not generate that record.')),
        ),
    },
}

# 同一主题的首屏只给用途与入口，参数、前提和练习放入可折叠小节。
TOPICS.update({
    'browse': {
        'title': ('开始阅片', 'Start browsing'),
        'intro': ('打开影像，找到切片，并安排适合当前任务的视图。', 'Open images, find a slice and arrange the views for your task.'),
        'steps': ('打开 DICOM 目录 → 选择序列 → 用滚轮或层数滑条浏览。需要更多影像空间时收起右侧面板。', 'Open a DICOM folder → select a series → browse with the wheel or slice slider. Hide the control panel for more image space.'),
        'sections': (
            (('切片、缩放与布局', 'Slices, zoom and layout'), ('普通滚轮切换切片；Ctrl＋滚轮缩放，左下角 Zoom 显示当前倍率。单窗、双窗、四窗改变视图排列，不增加数据分辨率。每个视图顶部可以选择方向；方向是否可用取决于影像几何信息。', 'Use the wheel for slices and Ctrl + wheel for zoom; the lower-left Zoom label shows the current scale. One-, two- and four-view layouts rearrange views without increasing data resolution. Select a plane above each view when image geometry supports it.')),
            (('播放与信息显示', 'Playback and information'), ('播放会在序列两端往返；慢、中、快对应不同刷新间隔，实际流畅度受电脑和影像大小影响。单层或未加载影像时不能播放。信息叠加控制角落文字；反色改变灰度显示。', 'Playback reverses at the series ends. Slow, medium and fast use different refresh intervals; actual smoothness depends on the computer and image size. Playback requires more than one slice. Information overlay controls corner text; inversion changes displayed greys.')),
            (('空白或不可用时', 'When empty or unavailable'), ('先看顶部工程状态和中央提示。打开工程不一定已经连接原始影像；此时按提示连接来源 DICOM。只能显示来源切片、不能选解剖方向时，可能是空间几何不足；不要把按钮禁用理解为影像中不存在该结构。', 'Check the project status and central message first. Opening a project may leave its source images disconnected; reconnect the source DICOM as prompted. If only source slices are available, spatial geometry may be insufficient for anatomical views. A disabled control says nothing about whether a structure exists in the image.')),
        ),
    },
    'mpr': {
        'title': ('多平面与投影', 'Planes and projections'),
        'intro': ('用不同方向观察同一体数据，或汇总一段厚度内的强度。', 'Inspect one volume in different planes, or combine intensities across a slab.'),
        'steps': ('在视图顶部选择方向；按需开启 MPR 联动。切换单层、MIP、MinIP 或平均投影 AIP，再调整层数。', 'Choose a view plane and enable MPR linking as needed. Select single slice, MIP, MinIP or average projection (AIP), then adjust the slice count.'),
        'sections': (
            (('方向和联动是什么', 'Planes and linking'), ('横断、冠状和矢状视图是体数据的不同截面。MPR 联动用于在多个方向定位同一空间位置；来源几何可证明时才开放。来源切片编号与解剖方向不是同一概念。', 'Axial, coronal and sagittal views are different sections of a volume. MPR linking locates one spatial position across views and requires supported source geometry. A source slice index is not itself an anatomical orientation.')),
            (('投影厚度的含义', 'Projection thickness'), ('MIP 取最大强度，MinIP 取最小强度，平均投影取平均强度。厚度控件以层数表示，范围 1–200；不是直接输入毫米，边界处可用范围还受数据限制。单层模式不使用这个参数，因此厚度输入禁用。', 'MIP takes maximum intensity, MinIP minimum intensity, and average projection the mean. Thickness is entered as 1–200 slices, not directly in millimetres; the available slab is limited at image boundaries. Single-slice mode does not use this control, so it is disabled.')),
            (('为什么不能在投影上编辑', 'Why projection editing is unavailable'), ('投影像素来自多层，不能唯一对应一张可编辑平面。需要画笔、测量或清理当前平面时，先返回单层，再确认目标视图与工作图层。帮助不会替你切换模式。', 'A projected pixel combines several slices and does not identify one editable plane. For painting, measurement or clearing a plane, return to single slice and check the target view and working layer. Help does not switch modes for you.')),
        ),
    },
    'roi': {
        'title': ('测量与 ROI', 'Measurement and ROI'),
        'intro': ('记录距离或区域，并理解读数采用的单位和数据来源。', 'Record distances or regions and understand the units and source of their measurements.'),
        'steps': ('选择可编辑的单层视图 → 选择测距或椭圆 ROI → 在影像上拖动 → 检查标注读数和标定提示。', 'Choose an editable single-slice view → select ruler or ellipse ROI → drag on the image → check the values and calibration message.'),
        'sections': (
            (('区域统计与窗位', 'Region statistics and windowing'), ('ROI 统计区域内的强度，调窗只改变显示。相同区域变亮并不表示原始强度增加。几何测量与 HU 是否可用由数据标定决定；未证明的单位不能通过选择预设获得。', 'ROI statistics describe intensity within the region; windowing changes display only. A brighter region need not have higher original intensity. Geometry and intensity calibration determine physical units and HU; selecting a preset cannot establish missing units.')),
            (('标注保存在哪里', 'Where measurements belong'), ('测量属于当前序列与来源平面，保存标注工程后可随工程恢复。切换序列时，参考标注可能以只读方式显示；它不是当前序列新画的标注。绘制前先核对视图方向和来源。', 'Measurements belong to the current series and source plane and can be restored from the saved annotation project. Reference annotations shown after a series switch may be read-only; they are not newly drawn measurements in this series. Check the plane and source before drawing.')),
            (('为什么无法标注或工具不可用', 'Why annotation or a tool is unavailable'), ('对比模式、重建模式、只读原始 AI 视图或未连接来源时不能按普通标注流程编辑；投影也不能作为单层编辑目标。强度标定或像素间距不足也可能限制工具。先检查标定与几何状态提示，不要用屏幕像素推断毫米。', 'Comparison, reconstruction, a read-only original AI view or disconnected source prevents normal annotation editing. A projection is not a single-slice editing target. Insufficient intensity calibration or pixel spacing may also limit tools. Check calibration and geometry status rather than inferring millimetres from screen pixels.')),
        ),
    },
    'annotation': {
        'title': ('标注与工作图层', 'Annotations and working layers'),
        'intro': ('在可编辑图层上修改范围，并保留原始 AI 版本供对照。', 'Edit regions on a working layer while retaining original AI versions for comparison.'),
        'steps': ('打开“标注”页 → 确认工作图层与画笔目标 → 在单层视图编辑。修改有误可按 Ctrl＋Z 撤销。', 'Open Annotations → check the working layer and brush target → edit a single-slice view. Use Ctrl + Z to undo a mistake.'),
        'sections': (
            (('工作图层和原始 AI', 'Working layers and original AI'), ('原始 AI 是只读版本。选择它只改变画面，不会把结果页统计改为这个版本。要以它继续修改，点“采用此 AI 版本为工作结果”；这会改变工作结果，而不仅是显示开关。', 'Original AI versions are read-only. Selecting one changes the display, not the working result used by the Results tab. Choose “Use this AI version as working result” to edit from that version; this changes the working result rather than merely its visibility.')),
            (('画笔和病灶图层', 'Brush and lesion layers'), ('画笔半径可选 0–40；0 显示为 1 voxel，表示单体素画笔，不是零大小。先选目标再画；橡皮用于擦除。新建病灶图层需要已连接的来源。关联参考病灶只建立同编号空图层，范围仍需在当前序列独立标注，不自动复制形状。', 'Brush radius ranges from 0 to 40; 0 is shown as “1 voxel” and means a single-voxel brush. Select a target before painting; use the eraser to remove labels. A new lesion layer requires a connected source. Linking a reference lesion creates an empty layer with the same lesion identifier; its extent must be annotated independently in this series.')),
            (('清理和撤销', 'Clearing and undo'), ('清理当前平面前，明确选择 V1–V4，并核对下面的方向和图层说明；隐藏或不能编辑的视图不可作为目标。清理当前平面与清空标注不是同一范围。撤销按钮只在存在可撤销历史时启用；保存工程不代表所有运行时历史都会永久保留。', 'Before clearing a plane, explicitly choose V1–V4 and verify its plane and layer description. Hidden or non-editable views cannot be targets. Clearing one plane and clearing annotations have different scopes. Undo is enabled when undo history exists; saving a project does not guarantee permanent storage of all runtime history.')),
        ),
    },
    'ai': {
        'title': ('AI 与结果导出', 'AI and result export'),
        'intro': ('区分原始预测、人工工作结果与统计输出，先核对来源再使用结果。', 'Distinguish original predictions, edited working results and statistics before using an output.'),
        'steps': ('打开“结果”页查看 AI 状态和统计来源。已有有效工作结果时可导出 CSV 或打开三维预览；模型信息可从模型说明卡查阅。', 'Open Results to inspect AI status and the statistics source. With valid working results, export CSV or open the 3-D preview; consult the model card for model information.'),
        'sections': (
            (('AI 如何开始或恢复', 'AI processing and restoration'), ('符合当前 CT 强度与几何条件的来源加载后，程序会检查可恢复结果，必要时走自动 AI 流程。没有兼容结果、缺少模型或来源条件不足时，不能假定已完成分割；以界面实际状态为准。手工编辑会停止当前自动流程，避免覆盖修改。查看帮助不会启动 AI。', 'For a source meeting the CT intensity and geometry conditions, loading checks for restorable results and may start automatic AI processing. Missing compatible results, models or source conditions do not imply completed segmentation; consult the displayed status. Manual editing stops the current automatic process to protect edits. Viewing help does not start AI.')),
            (('为什么 CSV 或三维按钮是灰色', 'Why CSV or 3-D is disabled'), ('这些按钮依赖非空工作统计、已连接影像和有效的 HU、方向、面内间距与均匀层间距。MRI 能手工标注不等于具备 CT 器官定量条件。三维预览还需所选目标实际有体素；目标没有范围时不能生成表面。', 'These controls require non-empty working statistics, connected images and valid HU, orientation, in-plane spacing and uniform slice spacing. Manual annotation on MRI does not imply support for CT organ statistics. A 3-D surface also requires voxels for the selected target; an empty target has no surface.')),
            (('读数和置信度怎样理解', 'Reading values and confidence'), ('结果页、CSV 和三维使用工作结果，可能与正在查看的只读原始 AI 不同。conf 是模型 softmax 最大类概率，p5 是其 5% 分位；人工改写体素不计入这类模型置信度。它们不是诊断概率，也不能替代人工核对。模型说明卡提供出处与适用边界。', 'Results, CSV and 3-D use the working result, which can differ from the read-only original AI currently displayed. conf is model softmax maximum probability and p5 its fifth percentile; manually overwritten voxels are excluded from that model confidence. These are not diagnostic probabilities or a substitute for review. The model card describes provenance and limitations.')),
        ),
    },
    'compare': {
        'title': ('序列与对比', 'Series and comparison'),
        'intro': ('区分同次检查的序列对应与独立的 CT 双序列对比。', 'Distinguish correspondence within a study from the separate CT comparison workflow.'),
        'steps': ('同次检查用序列下拉框切换；需要查看另一 CT 时，在“序列”页选择“加载对比序列”。结束后点“退出对比”。', 'Switch within a study using the series selector. For another CT, choose Load Comparison on the Series tab; choose Exit Compare when finished.'),
        'sections': (
            (('双序列对比看什么', 'Reading the comparison'), ('V1 显示当前序列，V2 显示对比序列，共享窗宽窗位。程序优先按切片空间位置匹配；标题会说明匹配或降级状态。默认双窗；额外显示差值时也要先检查是否同尺寸、同间距、处于覆盖范围。差值不等于病情变化。', 'V1 shows the current series and V2 the comparison series with shared window settings. Slice positions are matched where available; titles report matching or fallback status. Two views are used by default. Any difference display also depends on compatible dimensions, spacing and coverage. A difference is not itself a change in disease.')),
            (('两种配准不要混淆', 'Two different registration workflows'), ('对比页的“配准”是在层面内对齐，是否采用以标题为准；非方形像素时只允许平移。同次检查的“三维刚性配准”用于序列空间对应，是另一流程。参考标注只读显示；可靠对应不足时不应推断同一点。', 'Register in comparison aligns images within a slice; the title reports whether it was applied. Non-square pixels permit translation only. Study-series 3-D rigid registration is a separate spatial-correspondence workflow. Reference annotations are read-only; insufficient correspondence does not establish the same point.')),
            (('前提和返回后的状态', 'Requirements and returning'), ('双序列对比要求阅片模式下有效的 CT 强度和几何信息；普通 MRI 或几何不足的来源不能据此做 HU 对比。对比时隐藏不适用的平面控件并停止普通标注。退出且主来源未变时恢复原布局、MPR 与观察位置；换了来源不沿用旧相机位置。', 'Comparison requires valid CT intensity and geometry in browsing mode; ordinary MRI or insufficient geometry does not support this HU comparison. Inapplicable plane controls and normal annotation editing are unavailable during comparison. On exit, the original layout, MPR and camera are restored if the main source is unchanged; a changed source does not inherit the old camera.')),
        ),
    },
    'project': {
        'title': ('工程保存与来源', 'Projects and sources'),
        'intro': ('保存标注工作，并在重新打开时核对原始影像是否已连接。', 'Save annotation work and check source-image connections when reopening.'),
        'steps': ('用“保存标注工程”保存当前工作；用“打开工程”恢复。出现离线工程提示时，连接原始 DICOM 后继续影像操作。', 'Save the annotation project to preserve your work; use Open Project to restore it. Reconnect the original DICOM when an offline-project message appears.'),
        'sections': (
            (('工程和导出不是一回事', 'Project versus export'), ('工程 .miwproj 保存标注及相关来源信息，用于继续工作。定量 CSV 是结果表，三维导出是表面；它们不能替代工程。工程不打包原始 DICOM，也不保存重建实验全过程。', 'An .miwproj project preserves annotations and source-related information for continued work. A statistics CSV is a result table and a 3-D export is a surface; neither replaces the project. A project does not bundle original DICOM files or preserve the complete reconstruction experiment.')),
            (('为什么打开后没有影像', 'Why images may be absent'), ('原始文件位置改变或来源尚未连接时，工程仍可打开，但影像、AI 定量和编辑能力可能不可用。按中央提示连接正确的原始 DICOM；不要只凭患者名称或数组大小认定同一序列。程序会检查来源对应关系，拒绝不匹配的数据。', 'A moved or disconnected source may allow the project to open while images, AI statistics and editing remain unavailable. Reconnect the correct original DICOM as prompted. Patient name or array size alone does not identify a series; the application checks source correspondence and rejects mismatches.')),
            (('保存状态与脱敏', 'Save status and de-identification'), ('保存后看顶部状态是否成功；失败时当前工作仍需保留并重新处理保存。可在“序列”的数据与隐私区域选择或打开保存目录。屏幕脱敏只影响显示，不移除工程内部的来源标识，也不处理原始 DICOM。', 'Check the top status after saving; a failed save still requires preserving and saving the current work. Select or open the save directory in the Series data and privacy area. Display de-identification affects the screen, not internal project source identifiers or the original DICOM.')),
        ),
    },
})

TOPICS['window']['sections'] += (
    (('预设与每窗设置', 'Presets and per-view settings'),
     ('视图顶部可选独立预设；再次操作全局滑条、全局预设或右键调窗，会将可见视图切回“跟随”，统一使用全局窗宽窗位。MRI 的显示范围根据来源强度调整，CT 预设不一定可用。显示预览可用也不代表 HU 已标定；核对黄色状态提示。',
      'A view can use its own preset. Changing global sliders or presets, or windowing with the right mouse button, returns visible views to Global and applies the shared settings. MRI display ranges follow source intensity and CT presets may be unavailable. An available display preview does not establish HU calibration; check the status message.')),
)
TOPICS['recon']['sections'] += (
    (('按钮前提与画面用途', 'Control requirements and view roles'),
     ('BP、FBP、DFR 需要先生成弦图；CNN 后处理还需要对应模型可用。矩阵重建和迭代重建另有矩阵大小与方法设置，不应套用同一流程。\n\n在 FBP 对比流程中，V1 为来源、V2 为弦图、V3 为未滤波 BP、V4 为 FBP；其他算法会改变视图用途，以各窗口标题为准。单独运行 BP 的结果显示在 V4。',
      'BP, FBP and DFR require a generated sinogram; CNN post-processing additionally requires its model. Matrix and iterative reconstruction have their own size and method controls.\n\nIn the FBP comparison workflow, V1 is the source, V2 the sinogram, V3 unfiltered BP and V4 FBP. Other methods change these roles; read the window titles. Running BP alone places its result in V4.')),
    (('可选参数', 'Available settings'),
     ('角度范围：60°、120°、180°、360°；采样密度：1×、2×、4×。FBP 滤波器：Ram-Lak、Shepp-Logan、Cosine、Hamming、Hann。参数变化可能改变计算量与显示结果；不是越大就必然越好。先固定来源与其他设置，再改变一个参数。',
      'Angular ranges: 60°, 120°, 180° and 360°; sampling densities: 1×, 2× and 4×. FBP filters: Ram-Lak, Shepp-Logan, Cosine, Hamming and Hann. Settings affect computation and appearance; larger is not necessarily better. Fix the source and other settings before changing one parameter.')),
)

_GROUPS = {
    'browse': ('影像与显示', 'Images and display'),
    'window': ('影像与显示', 'Images and display'),
    'mpr': ('影像与显示', 'Images and display'),
    'roi': ('标注与结果', 'Annotations and results'),
    'annotation': ('标注与结果', 'Annotations and results'),
    'ai': ('标注与结果', 'Annotations and results'),
    'compare': ('序列与工程', 'Series and projects'),
    'project': ('序列与工程', 'Series and projects'),
    'recon': ('重建与学习', 'Reconstruction and learning'),
}
_RELATED = {
    'browse': ('window', 'mpr', 'project'), 'window': ('browse', 'roi', 'mpr'),
    'mpr': ('browse', 'annotation', 'compare'), 'roi': ('window', 'annotation', 'project'),
    'annotation': ('roi', 'ai', 'project'), 'ai': ('annotation', 'project', 'compare'),
    'compare': ('mpr', 'annotation', 'project'), 'project': ('browse', 'annotation', 'ai'),
    'recon': ('window', 'project'),
}
_ALIASES = {
    'browse': ('导入 DICOM 播放 滚轮 缩放 单窗 双窗 四窗', 'import DICOM cine playback wheel zoom layout'),
    'window': ('W L WW WL 调窗 反色 预设 HU', 'W L WW WL windowing invert preset HU'),
    'mpr': ('MPR MIP MinIP 平均 投影 厚度 层数', 'MPR MIP MinIP mean projection slab slices'),
    'roi': ('椭圆 测距 尺子 毫米 HU 区域 统计', 'ellipse ruler distance millimetres HU region statistics'),
    'annotation': ('画笔 橡皮 撤销 图层 病灶 原始 AI', 'brush eraser undo layer lesion original AI'),
    'ai': ('AI CSV STL 三维 分割 模型 置信度', 'AI CSV STL 3D segmentation model confidence'),
    'compare': ('随访 既往 当前 配准 参考 序列', 'follow-up prior current registration reference series'),
    'project': ('保存 打开 离线 连接 来源 脱敏 miwproj', 'save open offline reconnect source de-identification miwproj'),
    'recon': ('Radon Sinogram BP FBP DFR DMR ART SIRT ASD-POCS 模体 滤波器', 'Radon sinogram BP FBP DFR DMR ART SIRT ASD-POCS phantom filter'),
}
# 顺序同时用于目录浏览，分组及关联只表达查阅关系，不执行功能。
TOPICS = {key: dict(TOPICS[key], group=_GROUPS[key], related=_RELATED[key], aliases=_ALIASES[key])
          for key in _GROUPS}
TOPICS['window']['diagram'] = 'window'
TOPICS['recon']['diagram'] = 'recon'
TOPICS['annotation']['diagram'] = 'layers'
TOPICS['ai']['diagram'] = 'layers'


def search_topics(query, english=False):
    """无Qt全文搜索：返回可定位的小节与匹配摘要，不执行任何工作站操作。"""
    words = query.strip().casefold().split()
    if not words:
        return []
    lang = int(bool(english))
    matches = []
    for key, topic in TOPICS.items():
        title = topic['title'][lang]
        entries = [(None, '概览' if not lang else 'Overview', topic['intro'][lang] + ' ' + topic['steps'][lang])]
        entries.extend((i, heading[lang], body[lang]) for i, (heading, body) in enumerate(topic['sections']))
        for section, heading, body in entries:
            text = ' '.join(body.split())
            searchable = heading + ' ' + text
            if section is None:
                searchable = title + ' ' + searchable + ' ' + topic['aliases'][lang]
            folded = searchable.casefold()
            if not all(word in folded for word in words):
                continue
            positions = [text.casefold().find(word) for word in words if word in text.casefold()]
            start = max(0, min(positions) - 24) if positions else 0
            length = 100 if lang else 62
            snippet = ('…' if start else '') + text[start:start + length] + ('…' if start + length < len(text) else '')
            score = sum(8 * (word in title.casefold()) + 5 * (word in heading.casefold())
                        + 2 * (word in text.casefold()) for word in words)
            matches.append({'topic': key, 'section': section, 'title': title, 'heading': heading, 'snippet': snippet, 'score': score})
    return sorted(matches, key=lambda item: -item['score'])
