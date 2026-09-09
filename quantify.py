# =============================================================================
# 器官定量纯计算模块
# 负责：从分割蒙版 + HU 体积 + 体素尺寸算各器官的体积(mL)与平均 HU。
# 设计：无任何 Qt/UI 依赖，输入输出皆为普通 numpy 数组与 dict/list，
#       故可脱离 MedicalViewer 独立单元测试（见 tests/test_gui.py::test_quantify）。
#       AnnotationMixin._compute_organ_stats 只是读取 self 状态后调用本函数的薄包装。
# =============================================================================

from __future__ import annotations

import numpy as np


def compute_organ_stats(volume_hu: np.ndarray, volume_mask: np.ndarray,
                        spacing: tuple[float, float, float],
                        organ_names: dict[int, tuple[str, str]],
                        volume_conf: np.ndarray | None = None) -> list[dict]:
    """统计 volume_mask 中各标签的体积(mL)与 HU 一阶统计量，按体积降序返回。

    volume_hu:    3D HU 值体素数组，shape=(Z,H,W)
    volume_mask:  同形状的 uint8 标签图（0=背景，1-255=器官/手动层）
    spacing:      (行间距 ps0, 列间距 ps1, 层厚 st)，单位 mm
    organ_names:  {标签号: (中文名, 英文名)}；缺失标签回退为 "类{id}"/"cls{id}"
    volume_conf:  可选，同形状 uint8 置信度（255=1.0），来自 softmax 最大类概率。
                  给了才输出 mean_conf/p5_conf，没给则该键缺席——数学降级路径没有
                  概率输出，此时宁可不报，也不填一个看起来像置信度的数。
    返回:         [{'id','name_zh','name_en','voxels','volume_ml',
                    'mean_hu','sd_hu','median_hu','p5_hu','p95_hu','min_hu','max_hu'}, ...]，
                  给了 volume_conf 时另含 'mean_conf','p5_conf'（0-1）。
                  按 volume_ml 降序；无前景标签时返回 []。

    为何不止 mean：只报均值无法反映区域内的密度离散程度，而离散度正是判断分割是否
    误纳入邻近组织、以及做任何统计比较的前提（椭圆 ROI 一直给的是 mean±SD，
    器官定量此前只给 mean，两者口径不一致）。p5/p95 比 min/max 抗单体素噪声，
    故一并给出，min/max 仍保留供查看极端值。
    """
    ps0, ps1, st = spacing
    vox_ml = ps0 * ps1 * st / 1000.0  # 单体素体积，mm³ → mL
    # bincount 会把 uint8 输入加宽为平台整数；分块避免为整卷临时分配数百 MB。
    counts = np.zeros(256, np.int64)
    flat = volume_mask.ravel()
    for start in range(0, flat.size, 262144):
        counts += np.bincount(flat[start:start + 262144], minlength=256)
    present = [i for i in range(1, 256) if counts[i] > 0]
    if not present:
        return []
    rows = []
    for lid in present:
        zh, en = organ_names.get(lid, (f"类{lid}", f"cls{lid}"))
        # 百分位本就需要该标签的样本；均值/总体 SD 复用它，避免为两个手绘体素
        # 仍在 ndimage 中统计整卷背景、产生整卷 float64/整数临时数组。254/255 无加法溢出。
        sel = volume_mask == lid
        vals = volume_hu[sel]
        p5, med, p95 = np.percentile(vals, (5, 50, 95))
        row = {'id': lid, 'name_zh': zh, 'name_en': en, 'voxels': int(counts[lid]),
               'volume_ml': counts[lid] * vox_ml,
               'mean_hu': float(vals.mean(dtype=np.float64)), 'sd_hu': float(vals.std(dtype=np.float64)),
               'median_hu': float(med), 'p5_hu': float(p5), 'p95_hu': float(p95),
               'min_hu': float(vals.min()), 'max_hu': float(vals.max())}
        if volume_conf is not None and volume_conf.shape == volume_mask.shape:
            # conf==0 是哨兵，表示该体素没有模型置信度（手动 3D 追踪写入的、或被画笔
            # 改过的）。必须排除：它们的原值是模型对**改动前那个器官**的置信度，
            # 拿来当这个标签的置信度纯属张冠李戴。若整个标签都无模型体素
            # （手动追踪层就是这种），干脆不报——宁可没有，也不给一个假的。
            cv = volume_conf[sel]
            cv = cv[cv > 0].astype(np.float32) / 255.0
            if cv.size:
                # p5 一并给出：平均置信度会被大片确信的内部体素拉高，掩盖边界处的低置信，
                # 而分割出错恰恰多发生在边界——低分位比均值更能暴露问题
                row['mean_conf'] = float(cv.mean())
                row['p5_conf'] = float(np.percentile(cv, 5))
                # 模型判定过的体素占比：远小于 1 说明这个器官已被大量手工改动
                row['conf_cover'] = float(cv.size / max(1, int(counts[lid])))
        rows.append(row)
    rows.sort(key=lambda r: -r['volume_ml'])
    return rows
