#!/usr/bin/env python
# =============================================================================
# 里程碑 A 验收：两例真实 vestibular schwannoma MRI（VS-SEG-002 / VS-SEG-003）
# 的“载入 → 人工标注 → Undo → 保存 → 重开 → 标注仍在且空间不漂移”闭环。
#
# 数据来自 Annotation_Projects/recovered_vestibular_schwannoma_cases/（不入库，
# 见 .gitignore），本机不存在时跳过并给出明确原因，不伪造通过。
#
# 运行：conda activate dicom_gui && python tests/test_milestone_a_mri_workflow.py
# =============================================================================
import json
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import numpy as np

from project_store import capture_project_snapshot, load_project_snapshot, save_project_snapshot
from study_data import StudyDocument, read_series_directory

_CASES_DIR = os.path.join(_ROOT, 'Annotation_Projects', 'recovered_vestibular_schwannoma_cases')
_MANIFEST = os.path.join(_CASES_DIR, 'manifest.json')

_CHECKS = []


def check(cond, label):
    _CHECKS.append(bool(cond))
    print(('  PASS ' if cond else '  FAIL ') + label)
    if not cond:
        raise AssertionError(label)


def _run_case(case):
    print(f'=== {case["patient_id"]} ===')
    dicom_dir = os.path.join(_CASES_DIR, case['dicom_path'])
    check(os.path.isdir(dicom_dir), f'{case["patient_id"]} 的 DICOM 目录存在: {dicom_dir}')

    result = read_series_directory(dicom_dir)
    check(not result.warnings, f'{case["patient_id"]} 载入无告警: {result.warnings}')
    check(len(result.series) == 1, f'{case["patient_id"]} 恰好识别出一个序列')
    source = result.series[0]

    check(source.modality == 'MR', f'{case["patient_id"]} 模态识别为 MR')
    check(source.volume.shape[0] == case['frames'],
          f'{case["patient_id"]} 帧数与恢复记录一致 ({source.volume.shape[0]} == {case["frames"]})')
    check(source.source_binding is not None, f'{case["patient_id"]} 建立来源绑定（帧身份可证明）')
    check(source.geometry_binding is not None,
          f'{case["patient_id"]} 建立几何绑定（IOP/IPP/PixelSpacing 齐全，可患者空间编辑）')

    affine = np.asarray(source.geometry_binding['affine_lps'])
    check(affine.shape == (4, 4) and abs(np.linalg.det(affine[:3, :3])) > 1e-6,
          f'{case["patient_id"]} 体素到患者空间的 affine 非退化，方向有效')

    doc = StudyDocument(source.study_uid)
    doc.attach_sources([source])
    sid = source.series_uid
    record = doc.series[sid]
    shape = record.working_mask.shape
    check(shape == source.volume.shape, f'{case["patient_id"]} 编辑网格形状与体数据形状一致 {shape}')

    before_geometry = record.geometry_binding
    z, y, x = shape[0] // 2, shape[1] // 2, shape[2] // 2
    voxel = int(np.ravel_multi_index((z, y, x), shape))
    other_voxel = int(np.ravel_multi_index((z, y, x + 1), shape))

    # 一笔人工标注：只写入 working-manual 图层，working-organs 图层保持独立。
    doc.edit_mask(sid, [voxel], 255, layer_id='working-manual', description='manual paint')
    check(doc.series[sid].layers['working-manual'].mask.flat[voxel] == 255,
          f'{case["patient_id"]} 人工标注写入目标体素')
    check(doc.series[sid].layers['working-manual'].mask.flat[other_voxel] == 0,
          f'{case["patient_id"]} 人工标注不影响邻近体素（单体素精修）')
    check(not doc.series[sid].layers['working-organs'].mask.any(),
          f'{case["patient_id"]} 人工工作层与器官图层相互独立')
    check(len(doc.history) == 1, f'{case["patient_id"]} 一笔标注计一步历史')

    # Undo：真正回退该笔操作。
    doc.undo()
    check(doc.series[sid].layers['working-manual'].mask.flat[voxel] == 0,
          f'{case["patient_id"]} Undo 回退人工标注')
    check(len(doc.history) == 0, f'{case["patient_id"]} Undo 后历史清空')

    # 重新画一笔用于保存闭环（本仓库当前没有 Redo 栈，见里程碑报告的已知限制）。
    doc.edit_mask(sid, [voxel], 255, layer_id='working-manual', description='manual paint (2)')

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'study.miwproj')
        save_project_snapshot(capture_project_snapshot(doc), path)
        restored = load_project_snapshot(path)

        check(restored.series[sid].layers['working-manual'].mask.flat[voxel] == 255,
              f'{case["patient_id"]} 重开后标注仍在')
        check(restored.series[sid].geometry_binding == before_geometry,
              f'{case["patient_id"]} 重开后几何绑定逐字段一致，空间未漂移')
        check(len(restored.history) == 1, f'{case["patient_id"]} 重开后历史随工程恢复')

        restored.attach_sources([source])
        restored.undo()
        check(restored.series[sid].layers['working-manual'].mask.flat[voxel] == 0,
              f'{case["patient_id"]} 重开后仍可 Undo 最近一步编辑')

    print(f'{case["patient_id"]} PASS')


def main():
    if not os.path.isfile(_MANIFEST):
        print(f'WARN: 未找到 {_MANIFEST}，跳过里程碑 A 真实 MRI 闭环测试（本机未恢复该数据）')
        return 0
    with open(_MANIFEST, encoding='utf-8') as fh:
        manifest = json.load(fh)
    for case in manifest['cases']:
        _run_case(case)
    total, passed = len(_CHECKS), sum(_CHECKS)
    print(f'\n{passed}/{total} 项通过')
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
