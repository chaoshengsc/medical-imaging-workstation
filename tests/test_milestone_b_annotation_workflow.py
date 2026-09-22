#!/usr/bin/env python
# =============================================================================
# 里程碑 B 验收：人工标注工作流与工程文件，用 VS-SEG-002 / VS-SEG-003 真实 MRI。
#
# 对应 docs/AGENT_SYNC.md 里程碑 B 执行包 1-5 条：
#   1. 多笔跨切片/跨图层标注的保存→重开逐体素比对
#   2. 连续多步 Undo 的精确回退 + 20 步历史上限 + 跨重开续撤销
#   3. 单体素编辑只影响来源网格中的对应体素（含边界体素）
#   4. working-manual 与只读 AI 图层的数据模型隔离
#   5. 已知坏例：保存失败注入 / 来源不匹配 / 几何绑定篡改后的明确拒绝
#
# 数据来自 Annotation_Projects/recovered_vestibular_schwannoma_cases/（不入库，
# 见 .gitignore），本机不存在时跳过并给出明确原因，不伪造通过。
#
# 运行：conda activate dicom_gui && python tests/test_milestone_b_annotation_workflow.py
# =============================================================================
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import numpy as np

from project_store import (
    ProjectError,
    capture_project_snapshot,
    load_project_snapshot,
    save_project_snapshot,
)
from study_data import StudyDocument, read_series_directory

_CASES_DIR = os.path.join(_ROOT, 'Annotation_Projects', 'recovered_vestibular_schwannoma_cases')
_MANIFEST = os.path.join(_CASES_DIR, 'manifest.json')

_CHECKS = []


def check(cond, label):
    _CHECKS.append(bool(cond))
    print(('  PASS ' if cond else '  FAIL ') + label)
    if not cond:
        raise AssertionError(label)


def _rewrite_project(path, mutate):
    """只改临时合成包；重算摘要以确认语义门不是仅靠 checksum 拦截。"""
    with zipfile.ZipFile(path) as package:
        members = {name: package.read(name) for name in package.namelist()}
    manifest = json.loads(members['manifest.json'])
    mutate(manifest)
    members['manifest.json'] = json.dumps(manifest).encode()
    members['manifest.sha256'] = hashlib.sha256(members['manifest.json']).hexdigest().encode()
    with zipfile.ZipFile(path, 'w') as package:
        for name, data in members.items():
            package.writestr(name, data)


def _load_case(case):
    dicom_dir = os.path.join(_CASES_DIR, case['dicom_path'])
    source = read_series_directory(dicom_dir).series[0]
    doc = StudyDocument(source.study_uid)
    doc.attach_sources([source])
    return doc, source


def _case_1_multi_stroke_roundtrip(case):
    """跨切片/跨图层多笔标注：保存→重开后逐层逐体素全量比对。"""
    doc, source = _load_case(case)
    sid = source.series_uid
    shape = doc.series[sid].working_mask.shape

    manual_indices = [int(np.ravel_multi_index((z, 40, 40), shape)) for z in (0, 5, shape[0] // 2, shape[0] - 1)]
    organ_indices = [int(np.ravel_multi_index((z, 200, 300), shape)) for z in (2, shape[0] // 3, shape[0] - 2)]

    doc.edit_mask(sid, manual_indices, 255, layer_id='working-manual', description='跨切片人工标注')
    doc.edit_mask(sid, organ_indices, 7, layer_id='working-organs', description='跨切片器官标签')
    doc.edit_mask(sid, [manual_indices[1]], 0, layer_id='working-manual', description='橡皮擦局部撤回')

    expected_manual = doc.series[sid].layers['working-manual'].mask.copy()
    expected_organs = doc.series[sid].layers['working-organs'].mask.copy()
    check(expected_manual.flat[manual_indices[1]] == 0 and expected_manual.flat[manual_indices[0]] == 255,
          f'{case["patient_id"]} 橡皮只清除被擦的那一笔，其余人工标注保留')

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'multi.miwproj')
        save_project_snapshot(capture_project_snapshot(doc), path)
        restored = load_project_snapshot(path)
        check(np.array_equal(restored.series[sid].layers['working-manual'].mask, expected_manual),
              f'{case["patient_id"]} 重开后 working-manual 图层逐体素完全一致')
        check(np.array_equal(restored.series[sid].layers['working-organs'].mask, expected_organs),
              f'{case["patient_id"]} 重开后 working-organs 图层逐体素完全一致（两图层互不覆盖）')


def _case_2_precise_multi_undo_and_history_cap(case):
    """连续多步 Undo 精确回退到中间状态，且历史严格遵守最近 20 步上限。"""
    doc, source = _load_case(case)
    sid = source.series_uid
    shape = doc.series[sid].working_mask.shape

    n = 25
    voxels = [int(np.ravel_multi_index((z, 10, 10), shape)) for z in range(n)]
    for i, voxel in enumerate(voxels):
        doc.edit_mask(sid, [voxel], 255, layer_id='working-manual', description=f'stroke {i}')
    check(len(doc.history) == 20,
          f'{case["patient_id"]} {n} 笔互不相同的编辑后历史严格保持 20 步上限（实际 {len(doc.history)}）')
    check(all(doc.series[sid].layers['working-manual'].mask.flat[v] == 255 for v in voxels),
          f'{case["patient_id"]} 超出 20 步上限的早期编辑效果仍保留（不可撤销但不丢数据）')

    # 精确回退 5 步：只应影响最后 5 笔，其余 15 笔（仍在栈内）必须原样不动。
    for _ in range(5):
        doc.undo()
    check(all(doc.series[sid].layers['working-manual'].mask.flat[v] == 0 for v in voxels[-5:]),
          f'{case["patient_id"]} 回退 5 步精确撤销最后 5 笔')
    check(all(doc.series[sid].layers['working-manual'].mask.flat[v] == 255 for v in voxels[:-5]),
          f'{case["patient_id"]} 回退 5 步不影响栈内更早的 15 笔（非清空重画的近似效果）')
    check(len(doc.history) == 15, f'{case["patient_id"]} 回退 5 步后历史剩 15 步')

    # 继续回退到栈空：能撤销的 20 笔全部精确复原，20 步之外落地的 5 笔保持不可撤销的既成事实。
    for _ in range(15):
        doc.undo()
    check(len(doc.history) == 0, f'{case["patient_id"]} 历史可以撤销至空')
    check(all(doc.series[sid].layers['working-manual'].mask.flat[v] == 0 for v in voxels[5:]),
          f'{case["patient_id"]} 20 步内的编辑全部精确回退为 0')
    check(all(doc.series[sid].layers['working-manual'].mask.flat[v] == 255 for v in voxels[:5]),
          f'{case["patient_id"]} 落在 20 步窗口之外的最早 5 笔仍是既成事实，不因后续 Undo 复活为可撤销')

    # 重新做 3 笔，保存→重开，验证跨重开仍可继续精确 Undo。
    reopened_voxels = [int(np.ravel_multi_index((z, 30, 30), shape)) for z in range(3)]
    for i, voxel in enumerate(reopened_voxels):
        doc.edit_mask(sid, [voxel], 255, layer_id='working-manual', description=f'post-cap stroke {i}')
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'undo_cap.miwproj')
        save_project_snapshot(capture_project_snapshot(doc), path)
        restored = load_project_snapshot(path)
        check(len(restored.history) == 3, f'{case["patient_id"]} 重开后历史步数与保存时一致')
        restored.attach_sources([source])
        restored.undo(); restored.undo()
        check(restored.series[sid].layers['working-manual'].mask.flat[reopened_voxels[2]] == 0
              and restored.series[sid].layers['working-manual'].mask.flat[reopened_voxels[1]] == 0
              and restored.series[sid].layers['working-manual'].mask.flat[reopened_voxels[0]] == 255,
              f'{case["patient_id"]} 重开后连续两步 Undo 按正确的后进先出顺序精确回退')


def _case_3_single_voxel_boundary_edits(case):
    """单体素编辑只影响来源网格中对应体素，覆盖切片/行/列三个方向的边界。"""
    doc, source = _load_case(case)
    sid = source.series_uid
    shape = doc.series[sid].working_mask.shape
    z_max, y_max, x_max = shape[0] - 1, shape[1] - 1, shape[2] - 1

    boundary_coords = [
        (0, 0, 0), (z_max, y_max, x_max),
        (0, y_max, 0), (z_max, 0, x_max),
        (z_max // 2, 0, x_max // 2), (z_max // 2, y_max, x_max // 2),
        (z_max // 2, y_max // 2, 0), (z_max // 2, y_max // 2, x_max),
    ]
    for coord in boundary_coords:
        voxel = int(np.ravel_multi_index(coord, shape))
        before = doc.series[sid].layers['working-manual'].mask.copy()
        doc.edit_mask(sid, [voxel], 255, layer_id='working-manual', description=f'boundary {coord}')
        after = doc.series[sid].layers['working-manual'].mask
        diff = np.flatnonzero((after != before).ravel())
        check(list(diff) == [voxel],
              f'{case["patient_id"]} 边界体素 {coord} 编辑只改变自身，不越界到相邻体素')
        doc.undo()

    for bad_index in (-1, int(np.prod(shape)), int(np.prod(shape)) + 1000):
        try:
            doc.edit_mask(sid, [bad_index], 255, layer_id='working-manual', description='out of range')
            rejected = False
        except ValueError:
            rejected = True
        check(rejected, f'{case["patient_id"]} 越界体素索引 {bad_index} 被拒绝，不静默钳制到边缘')
    check(len(doc.history) == 0, f'{case["patient_id"]} 越界拒绝不产生历史记录')


def _case_4_manual_and_ai_layer_isolation(case):
    """working-manual 与 AI 图层在数据模型上物理隔离；无真实旧 AI 数据时如实说明。"""
    doc, source = _load_case(case)
    sid = source.series_uid
    shape = doc.series[sid].working_mask.shape
    manual_voxel = int(np.ravel_multi_index((3, 50, 50), shape))
    organ_voxel = int(np.ravel_multi_index((3, 60, 60), shape))

    doc.edit_mask(sid, [manual_voxel], 255, layer_id='working-manual', description='manual only')
    doc.edit_mask(sid, [organ_voxel], 9, layer_id='working-organs', description='organ only')
    manual_mask = doc.series[sid].layers['working-manual'].mask
    organ_mask = doc.series[sid].layers['working-organs'].mask
    check(not np.shares_memory(manual_mask, organ_mask),
          f'{case["patient_id"]} working-manual 与 working-organs 是不同的底层数组')
    check(manual_mask.flat[organ_voxel] == 0 and organ_mask.flat[manual_voxel] == 0,
          f'{case["patient_id"]} 两个图层的编辑互不可见')

    # VS-SEG-002/003 是本次恢复的公开研究病例，没有随附任何历史 AI 推理缓存或权重产物；
    # 这里只用 add_ai_result 这个既有 API 契约本身做「只读版本与工作层隔离」的结构验证，
    # 不代表、也不冒充这两例真的跑过 AI 推理或存在可考的历史模型输出。
    print(f'[{case["patient_id"]}] 无真实旧 AI 缓存可用于本轮验证；下方只验证 add_ai_result 的隔离契约本身。')
    synthetic_ai_mask = np.zeros(shape, dtype=np.uint8)
    synthetic_ai_mask[0, 0, 0] = 5
    version = doc.add_ai_result(sid, synthetic_ai_mask, None, {'origin': 'contract-check-only'})
    ai_layer = doc.series[sid].layers[version]
    check(ai_layer.readonly, f'{case["patient_id"]} 新接入的 AI 结果版本只读')
    try:
        ai_layer.mask[0, 0, 0] = 0
        writable = True
    except ValueError:
        writable = False
    check(not writable, f'{case["patient_id"]} 只读 AI 图层的底层数组确实不可写（不是约定上只读）')
    doc.edit_mask(sid, [manual_voxel], 0, layer_id='working-manual', description='erase manual')
    check(ai_layer.mask[0, 0, 0] == 5, f'{case["patient_id"]} 编辑工作层不影响已接入的只读 AI 版本')


def _case_5_known_bad_rejections(case):
    """已知坏例：保存失败、来源不匹配、几何绑定篡改，均须明确拒绝，不静默损坏。"""
    doc, source = _load_case(case)
    sid = source.series_uid
    shape = doc.series[sid].working_mask.shape
    voxel = int(np.ravel_multi_index((1, 1, 1), shape))
    doc.edit_mask(sid, [voxel], 255, layer_id='working-manual', description='before failure')

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'known_bad.miwproj'
        save_project_snapshot(capture_project_snapshot(doc), path)
        original = path.read_bytes()

        doc.edit_mask(sid, [voxel + 1], 255, layer_id='working-manual', description='new edit before injected failure')
        for target in ('project_store._json_bytes', 'project_store.np.savez_compressed', 'project_store.os.replace'):
            with patch(target, side_effect=OSError('synthetic disk failure')):
                try:
                    save_project_snapshot(capture_project_snapshot(doc), path)
                    saved = True
                except OSError:
                    saved = False
            check(not saved and path.read_bytes() == original,
                  f'{case["patient_id"]} 注入 {target} 磁盘失败后拒绝保存，旧工程逐字节保留')
            check(not list(Path(tmp).glob('.miwproj-*.tmp')),
                  f'{case["patient_id"]} 失败的保存不残留临时文件')

        restored = load_project_snapshot(path)
        forged = replace(source, source_binding={**source.source_binding, 'digest': '0' * 64})
        try:
            restored.attach_sources([forged])
            attached = True
        except ValueError:
            attached = False
        check(not attached and restored.series[sid].source is None,
              f'{case["patient_id"]} 来源身份（source_binding 摘要）被篡改后拒绝接入，且不部分接入')

        tampered_path = Path(tmp) / 'tampered_geometry.miwproj'
        import shutil
        shutil.copy(path, tampered_path)

        def _break_affine(manifest):
            meta = next(m for m in manifest['series'] if m['series_uid'] == sid)
            affine = meta['geometry_binding']['affine_lps']
            affine[0] = [0.0, 0.0, 0.0, affine[0][3]]  # 破坏方向矩阵，使其退化（det=0）

        _rewrite_project(tampered_path, _break_affine)
        try:
            load_project_snapshot(tampered_path)
            loaded = True
        except ProjectError:
            loaded = False
        check(not loaded,
              f'{case["patient_id"]} 几何绑定被篡改为退化矩阵后，重开被拒绝（语义校验而非仅靠 checksum）')


def main():
    if not os.path.isfile(_MANIFEST):
        print(f'WARN: 未找到 {_MANIFEST}，跳过里程碑 B 真实 MRI 标注工作流测试（本机未恢复该数据）')
        return 0
    with open(_MANIFEST, encoding='utf-8') as fh:
        manifest = json.load(fh)
    for case in manifest['cases']:
        print(f'=== {case["patient_id"]} ===')
        _case_1_multi_stroke_roundtrip(case)
        _case_2_precise_multi_undo_and_history_cap(case)
        _case_3_single_voxel_boundary_edits(case)
        _case_4_manual_and_ai_layer_isolation(case)
        _case_5_known_bad_rejections(case)
        print(f'{case["patient_id"]} PASS')
    total, passed = len(_CHECKS), sum(_CHECKS)
    print(f'\n{passed}/{total} 项通过')
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
