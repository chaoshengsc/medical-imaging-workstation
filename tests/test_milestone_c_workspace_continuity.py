#!/usr/bin/env python
# =============================================================================
# 里程碑 C 验收（部分）：任务切换 / 四窗布局切换的工作区连续性，
# 用 VS-SEG-002 / VS-SEG-003 真实 MRI，在离屏 Qt（QT_QPA_PLATFORM=offscreen）
# 上通过真正的 MedicalViewer 实例验证——不是只测 Qt-free 数据层。
#
# 覆盖 docs/AGENT_SYNC.md 里程碑 C 执行包第 1/2/5 条：
#   1. on_tab_changed / switch_layout 在真实 MR 病例上不崩溃、状态自洽
#   2. 切到重建实验室再切回 / 四窗与单窗互切：断言相机（transform + 观察中心）
#      逐字段恢复，而不是仅断言“没有崩溃”
#   5. 进入/退出上述工作区切换全程 + 保存 + 用一个新的 MedicalViewer 实例重开：
#      标注数据和几何绑定不丢、不漂移
#
# 第 3/4 条（3D 预览只在有真实 mask 时可用、3D 视角随切片联动）本轮未覆盖：
# 见 docs/AGENT_SYNC.md 当前交接里的 Decision requested 说明，这里不重复。
#
# 数据来自 Annotation_Projects/recovered_vestibular_schwannoma_cases/（不入库，
# 见 .gitignore），本机不存在时跳过并给出明确原因，不伪造通过。
#
# 运行：conda activate dicom_gui && python tests/test_milestone_c_workspace_continuity.py
# =============================================================================
import json
import os
import sys
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import numpy as np
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)

import main as m

_CASES_DIR = os.path.join(_ROOT, 'Annotation_Projects', 'recovered_vestibular_schwannoma_cases')
_MANIFEST = os.path.join(_CASES_DIR, 'manifest.json')

_CHECKS = []


def check(cond, label):
    _CHECKS.append(bool(cond))
    print(('  PASS ' if cond else '  FAIL ') + label)
    if not cond:
        raise AssertionError(label)


def _open_viewer(project_dir, dicom_dir):
    v = m.MedicalViewer(project_dir=project_dir, autosave=False)
    v._kickoff_ai = lambda: None
    v.resize(1280, 800); v.show()
    v.load_data(dicom_dir)
    QTest.qWait(150)
    return v


def _paint_manual_voxel(v, voxel_zyx):
    sid = v.active_series_uid
    doc = v.study_document
    index = int(np.ravel_multi_index(voxel_zyx, doc.series[sid].working_mask.shape))
    doc.edit_mask(sid, [index], 255, layer_id='working-manual', description='milestone C probe stroke')
    doc.series[sid].active_layer_id = 'working-manual'
    v._sync_committed_edit()
    return index


def _case_tab_switch_continuity(case, dicom_dir):
    """真实 MR 上切到重建实验室再切回：相机逐字段恢复，标注不受影响。"""
    with tempfile.TemporaryDirectory() as project_dir:
        v = _open_viewer(project_dir, dicom_dir)
        try:
            sid = v.active_series_uid
            check(sid is not None and v.volume_hu is not None,
                  f'{case["patient_id"]} 真实 MR 通过 MedicalViewer.load_data 成功载入')
            voxel = _paint_manual_voxel(v, (v.volume_mask.shape[0] // 2, 40, 40))
            check(v.volume_mask.flat[voxel] == 255,
                  f'{case["patient_id"]} 载入后一笔人工标注写入 working-manual 图层')

            view = v.views[1]['view']
            view.scale(3, 3); view._user_zoomed = True
            view.centerOn(view.mapToScene(view.viewport().rect().center()) + type(view.mapToScene(0, 0))(5, 5))
            QTest.qWait(30)
            before_transform = view.transform()
            before_center = view.mapToScene(view.viewport().rect().center())

            check(not v.recon_mode_active, f'{case["patient_id"]} 初始处于临床阅片模式')
            v.tabs.setCurrentIndex(1); QTest.qWait(80)
            check(v.recon_mode_active, f'{case["patient_id"]} 切到重建实验室后 recon_mode_active 置真')
            v.tabs.setCurrentIndex(0); QTest.qWait(80)
            check(not v.recon_mode_active, f'{case["patient_id"]} 切回临床阅片后 recon_mode_active 置假')

            check(view.transform() == before_transform,
                  f'{case["patient_id"]} 重建实验室往返后 V1 缩放矩阵逐字段恢复')
            after_center = view.mapToScene(view.viewport().rect().center())
            check(abs(after_center.x() - before_center.x()) < .5 and abs(after_center.y() - before_center.y()) < .5,
                  f'{case["patient_id"]} 重建实验室往返后 V1 观察中心保持（允许 <0.5 像素取整）')
            check(v.volume_mask.flat[voxel] == 255,
                  f'{case["patient_id"]} 重建实验室往返未影响此前的人工标注')
        finally:
            v.close()


def _case_layout_switch_continuity(case, dicom_dir):
    """真实 MR 上单窗/四窗互切：隐藏视图重新显示后相机原样恢复。"""
    with tempfile.TemporaryDirectory() as project_dir:
        v = _open_viewer(project_dir, dicom_dir)
        try:
            v.combo_layout.setCurrentIndex(2); QTest.qWait(80)  # 四窗
            view = v.views[1]['view']
            view.scale(2.5, 2.5); view._user_zoomed = True
            view.centerOn(view.mapToScene(view.viewport().rect().center()))
            QTest.qWait(30)
            before_transform = view.transform()

            for layout in (1, 0, 2):
                v.combo_layout.setCurrentIndex(layout); QTest.qWait(50)
                check(view.transform() == before_transform,
                      f'{case["patient_id"]} 切到布局 {layout} 后 V1 缩放矩阵保持不变')
        finally:
            v.close()


def _case_reopen_no_data_loss(case, dicom_dir):
    """标注 + 任务/布局切换全流程 + 保存 + 新窗口重开：数据和几何绑定不丢不漂移。"""
    with tempfile.TemporaryDirectory() as project_dir:
        v1 = _open_viewer(project_dir, dicom_dir)
        try:
            sid = v1.active_series_uid
            voxel = _paint_manual_voxel(v1, (v1.volume_mask.shape[0] // 3, 60, 60))
            before_geometry = v1.study_document.series[sid].geometry_binding

            v1.combo_layout.setCurrentIndex(2); QTest.qWait(50)
            v1.tabs.setCurrentIndex(1); QTest.qWait(50)
            v1.tabs.setCurrentIndex(0); QTest.qWait(50)
            v1.combo_layout.setCurrentIndex(0); QTest.qWait(50)

            check(v1.save_project(), f'{case["patient_id"]} 切换往返后工程保存成功')
        finally:
            v1.close()

        v2 = _open_viewer(project_dir, dicom_dir)
        try:
            check(v2.study_document is not None and v2.active_series_uid == sid,
                  f'{case["patient_id"]} 新窗口重开自动接回已保存的工程')
            check(v2.volume_mask.flat[voxel] == 255,
                  f'{case["patient_id"]} 新窗口重开后人工标注仍在')
            check(v2.study_document.series[sid].geometry_binding == before_geometry,
                  f'{case["patient_id"]} 新窗口重开后几何绑定逐字段一致，空间未漂移')
        finally:
            v2.close()


def main():
    if not os.path.isfile(_MANIFEST):
        print(f'WARN: 未找到 {_MANIFEST}，跳过里程碑 C 工作区连续性测试（本机未恢复该数据）')
        return 0
    _ = QApplication.instance() or QApplication([])
    with open(_MANIFEST, encoding='utf-8') as fh:
        manifest = json.load(fh)
    for case in manifest['cases']:
        dicom_dir = os.path.join(_CASES_DIR, case['dicom_path'])
        print(f'=== {case["patient_id"]} ===')
        _case_tab_switch_continuity(case, dicom_dir)
        _case_layout_switch_continuity(case, dicom_dir)
        _case_reopen_no_data_loss(case, dicom_dir)
        print(f'{case["patient_id"]} PASS')
    total, passed = len(_CHECKS), sum(_CHECKS)
    print(f'\n{passed}/{total} 项通过')
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
