# =============================================================================
# 标注与分割 Mixin
# 负责：标注（卡尺/画笔/ROI）CRUD 与渲染、分割蒙版手动编辑（画笔/橡皮/3D 追踪/
#       撤销）、截取统计、器官定量与图例、标注/蒙版工程持久化。
#
# 设计：以 Mixin 形式并入 MedicalViewer。方法通过 self 访问主窗口的 UI 控件与
#       状态（self.views / self.volume_hu / self.volume_mask / self.global_annotations /
#       self._organ_stats / self.organ_names 等）及留在 main.py 的共享方法
#       （_read_dicom_dir / _dcm_float / _safe_name / _export_tag / update_display）。
#       状态（volume_mask / global_annotations / _mask_undo / _hidden_organs /
#       _organ_stats）在 MedicalViewer.__init__ 中初始化；_render_clinical_plane
#       对 _render_annotations、update_display 对 _update_legend 的调用留在 main。
# =============================================================================

import csv
import hashlib
import json
import math
import os
import uuid
from copy import deepcopy
from datetime import datetime
from threading import Event

import numpy as np
import scipy.ndimage as ndimage
from PySide6.QtCore import (
    QEventLoop,
    QLineF,
    QPointF,
    QSettings,
    QSignalBlocker,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsTextItem,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
)

import mesh3d
import model_card
import mpr_geometry
import quantify
import series_registration
from constants import AXIAL, CORONAL, LABEL_LUT, MANUAL_TRACK_LABEL, SAGITTAL, TOOL_SEG_BRUSH
from dicom_geometry import SeriesGeometry, series_fingerprint
from graphics_view import ROIGraphicsItem
from project_store import (
    HistoryRecoveryRequired,
    ProjectError,
    capture_project_snapshot,
    load_project_snapshot,
    save_project_snapshot,
)


class ProjectSaveWorker(QThread):
    """只压缩不可变快照并写盘；结果由 finished 信号交回主线程。"""

    def __init__(self, snapshot, path, generation, parent=None):
        super().__init__(parent)
        self.snapshot, self.path, self.generation = snapshot, path, generation
        self.receipt, self.error = None, None

    def run(self):
        try:
            self.receipt = save_project_snapshot(self.snapshot, self.path)
        except Exception as exc:
            self.error = str(exc)


class SeriesRegistrationWorker(QThread):
    """只计算冻结的影像来源；主线程负责接入结果和复核。"""

    def __init__(self, moving, fixed, document_id, revision, generation, parent=None):
        super().__init__(parent)
        self.moving, self.fixed = moving, fixed
        self.document_id, self.revision, self.generation = document_id, revision, generation
        self.cancelled = Event(); self.result = None; self.error = None

    def run(self):
        try:
            self.result = series_registration.register_rigid_3d(self.moving, self.fixed, cancelled=self.cancelled.is_set)
        except Exception as exc:
            self.error = str(exc)


class RegistrationReviewDialog(QDialog):
    """三个患者平面的当前/变换后参考/叠加预览；采用仅表示用户完成视觉复核。"""

    def __init__(self, moving, fixed, result, english=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Review 3-D alignment' if english else '检查三维配准对应')
        self.resize(940, 720)
        layout = QVBoxLayout(self)
        note = QLabel('Inspect anatomy through the three planes before accepting. Metric improvement alone does not prove alignment.'
                      if english else '请逐层检查三个方向的解剖对应。分数改善不能单独证明对齐；采用后记录为人工复核。')
        note.setWordWrap(True); layout.addWidget(note)
        grid = QGridLayout(); layout.addLayout(grid)
        for column, name in enumerate(('Current series', 'Aligned reference', 'Overlay') if english else ('当前序列', '变换后的参考序列', '叠加检查')):
            grid.addWidget(QLabel(name), 0, column + 1)
        self.sliders = []; self.previews = []
        plane_cursors = [mpr_geometry.patient_plane_cursors(fixed.affine, fixed.volume.shape, plane)
                         for plane in (AXIAL, CORONAL, SAGITTAL)]

        def gray(values):
            lo, hi = np.percentile(values, [1, 99])
            return np.clip((values - lo) / max(float(hi-lo), 1e-6) * 255, 0, 255).astype(np.uint8)

        def render(plane_index, index):
            cursor = plane_cursors[plane_index][index]
            plane = mpr_geometry.patient_plane(fixed.affine, fixed.volume.shape, plane_index, cursor)
            base = gray(plane.sample(fixed.volume))
            reference = gray(series_registration.sample_corresponding_plane(moving, fixed, moving.volume,
                                    plane, result, allow_candidate=True))
            mixed = np.stack((base, reference, base), axis=-1)
            # 预览与主视图一样按物理宽高比显示，不能把异方性像素当成正方形。
            aspect = plane.shape[1] * plane.spacing[1] / (plane.shape[0] * plane.spacing[0])
            width = max(1, min(240, round(150 * aspect)))
            height = max(1, min(150, round(240 / aspect)))
            for label, array in zip(self.previews[plane_index], (np.repeat(base[...,None],3,axis=2),
                                    np.repeat(reference[...,None],3,axis=2), mixed), strict=True):
                array = np.ascontiguousarray(array)
                image = QImage(array.data, array.shape[1], array.shape[0], array.strides[0], QImage.Format_RGB888).copy()
                label.setPixmap(QPixmap.fromImage(image).scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

        for plane_index, name in enumerate(('Axial', 'Coronal', 'Sagittal')):
            grid.addWidget(QLabel(name), plane_index * 2 + 1, 0)
            labels = [QLabel() for _ in range(3)]; self.previews.append(labels)
            for column, label in enumerate(labels):
                label.setAlignment(Qt.AlignCenter); label.setMinimumSize(180, 120)
                grid.addWidget(label, plane_index * 2 + 1, column + 1)
            slider = QSlider(Qt.Horizontal); slider.setRange(0, len(plane_cursors[plane_index]) - 1)
            slider.setValue(slider.maximum() // 2)
            slider.valueChanged.connect(lambda value, p=plane_index: render(p, value))
            self.sliders.append(slider); grid.addWidget(slider, plane_index * 2 + 2, 1, 1, 3)
            render(plane_index, slider.value())
        buttons = QHBoxLayout(); layout.addLayout(buttons)
        keep = QPushButton('Keep candidate' if english else '仅保留候选'); keep.clicked.connect(self.reject)
        accept = QPushButton('Reviewed all planes — adopt' if english else '已检查三面，采用'); accept.clicked.connect(self.accept)
        buttons.addWidget(keep); buttons.addWidget(accept)


class MeshView(QLabel):
    """可用鼠标拖动旋转的三维预览控件。

    横向拖动改方位角、纵向拖动改俯仰角，灵敏度 0.5°/px（实测这个值在 360px 视图上
    拖过半屏正好转半圈，手感接近常见的三维查看器）。俯仰角夹在 ±89°：到 ±90° 时
    视线与旋转轴共线，方位角失去意义（万向节锁），画面会在拖动中突然翻转。

    自身只负责「把像素位移换算成角度并发信号」，不碰网格与渲染——渲染策略
    （拖动降质、松手提质）由弹窗持有，因为只有它知道两套网格。
    """
    rotated = Signal(float, float)   # (azimuth, elevation)，已累积的绝对角度
    settled = Signal()               # 松开鼠标：可以做高质量重渲染了

    def __init__(self, azimuth=30.0, elevation=20.0, parent=None):
        super().__init__(parent)
        self.azimuth, self.elevation = float(azimuth), float(elevation)
        self._last = None
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, ev):
        self._last = ev.position(); self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if self._last is None: return
        p = ev.position(); dx = p.x() - self._last.x(); dy = p.y() - self._last.y()
        self._last = p
        self.azimuth = (self.azimuth + dx * 0.5) % 360.0
        self.elevation = max(-89.0, min(89.0, self.elevation - dy * 0.5))
        self.rotated.emit(self.azimuth, self.elevation)

    def mouseReleaseEvent(self, ev):
        if self._last is None: return
        self._last = None; self.setCursor(Qt.OpenHandCursor); self.settled.emit()

    def set_angles(self, azimuth, elevation):
        """由预设视角按钮调用：直接跳到指定角度（同样走 rotated → settled 两步）。"""
        self.azimuth = float(azimuth) % 360.0
        self.elevation = max(-89.0, min(89.0, float(elevation)))
        self.rotated.emit(self.azimuth, self.elevation); self.settled.emit()


def mask_cache_matches(saved_uid, saved_shape, saved_fingerprint,
                       cur_uid, cur_shape, cur_fingerprint):
    """判断磁盘缓存的分割蒙版能否安全恢复到当前序列（纯函数，无 Qt，可独立单测）。

    只比 shape 是不够的：缓存按 PatientID 命名，而同一患者的随访/复扫序列
    （本软件的双序列对比功能正是为此设计）往往同为 512×512×N —— 只按 shape 匹配
    会把 A 序列的蒙版静默套到 B 序列上，器官定量随之给出错误体积且无任何告警。
    故要求 SeriesInstanceUID 严格相等；缓存或当前序列缺 UID 时一律拒绝：
    宁可重跑 AI，也不返回可能张冠李戴的蒙版。

    返回 (是否可恢复, 拒绝原因)；可恢复时原因为 ''。
    """
    if tuple(saved_shape) != tuple(cur_shape):
        return False, f"shape 不匹配（缓存 {tuple(saved_shape)} vs 当前 {tuple(cur_shape)}）"
    if not saved_uid:
        return False, "缓存未记录 SeriesInstanceUID（旧版本产物），无法确认是否同一序列"
    if not cur_uid:
        return False, "当前序列缺 SeriesInstanceUID，无法确认与缓存是否同源"
    if str(saved_uid) != str(cur_uid):
        return False, "SeriesInstanceUID 不同（同一患者的另一序列），拒绝套用"
    if not saved_fingerprint:
        return False, "缓存缺 geometry/order fingerprint（legacy），无法证明切片对应关系"
    if not cur_fingerprint:
        return False, "当前序列无法生成 geometry/order fingerprint，拒绝自动恢复"
    if str(saved_fingerprint) != str(cur_fingerprint):
        return False, "geometry/order fingerprint 不同，拒绝把缓存套到不同切片顺序"
    return True, ""


# AI 分割输出的轴向契约标识。修复推理左右轴之前落盘的蒙版，其 W 轴是镜像的
# （成对器官标签互换），但 SeriesInstanceUID、shape 与 geometry fingerprint
# 三项都不会因此改变——既有三项守卫识别不出它。故显式记录契约并单独判定。
MASK_AXIS_CONTRACT = 'dicom-cols-left/v2'


def mask_axis_contract_ok(saved_contract):
    """缓存蒙版的轴向契约是否与当前推理路径一致（纯函数，无 Qt，可独立单测）。

    缺失即视为修复前的产物：那批蒙版左右镜像，宁可重跑 AI 也不恢复。
    """
    if not saved_contract:
        return False, "缓存未记录轴向契约（AI 左右方向修复前的产物，蒙版左右镜像）"
    if str(saved_contract) != MASK_AXIS_CONTRACT:
        return False, (f"轴向契约不同（缓存 {saved_contract} vs 当前 {MASK_AXIS_CONTRACT}）")
    return True, ""


# 顶层弹窗的系统背景可能为深色，必须同时设置前景 / 背景，不能假定浅色系统主题。
_DIALOG_FG = '#C9D1D9'
_DIALOG_FG_MUTED = '#9BAABD'
_DIALOG_STYLE = f"""
    QDialog, QLabel, QScrollArea {{ background-color: #1D232C; color: {_DIALOG_FG}; }}
    QScrollArea {{ border: 1px solid #344151; }}
    QPushButton {{ background-color: #283241; color: {_DIALOG_FG};
                   border: 1px solid #44546A; border-radius: 4px; padding: 7px; }}
    QPushButton:hover {{ background-color: #36465C; }}
    QScrollBar:vertical {{ background: #1D232C; width: 12px; }}
    QScrollBar::handle:vertical {{ background: #536175; min-height: 24px; border-radius: 5px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: #1D232C; }}
"""


def _pin_text_to_screen(txt, view):
    """让场景内的文字项保持屏幕固定大小，并返回它折算到场景单位的 (宽, 高)。

    默认情况下 QGraphicsTextItem 的字号定义在场景坐标里，会随视图缩放一起放大：
    512² 的序列铺满窗口时缩放常在 2.5–3.5×，标注文字随之涨到原来的三倍多，压住
    它所描述的解剖并溢出图像边界。置 ItemIgnoresTransformations 后字号锚定在屏幕
    像素上，缩放只改变锚点位置、不改变字的大小。

    返回值用于边界判断：文字的屏幕尺寸是固定的，但要和场景坐标里的图像宽高比较，
    必须先按当前缩放折算回去——写死一个场景单位常量在任何别的缩放下都是错的。
    """
    txt.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
    bounds = txt.boundingRect()  # 包括 QTextDocument 的真实边距，不能只量字体字宽。
    transform = view.transform()
    return (bounds.width() / (abs(transform.m11()) or 1.0),
            bounds.height() / (abs(transform.m22()) or 1.0))


class AnnotationMixin:
    """标注 / 分割蒙版编辑 / 器官定量相关方法集合，混入 MedicalViewer。"""

    def _capture_edit_context(self, vid):
        self._stop_cine()
        self._last_edit_vid = vid
        doc = self.study_document
        vd = self.views[vid]
        if doc is None or self.active_series_uid not in doc.series or not self._view_editable(vd):
            vd['view'].edit_context = None
            return
        record = doc.series[self.active_series_uid]
        layer_id = record.active_layer_id
        if (vd['view'].current_tool == TOOL_SEG_BRUSH
                and int(self.cb_paint_target.currentData() or MANUAL_TRACK_LABEL) == MANUAL_TRACK_LABEL
                and record.layers[layer_id].kind == 'organ'):
            layer_id = 'working-manual'
        vd['view'].edit_context = {
            'document_id': doc.document_id, 'series_uid': self.active_series_uid,
            'layer_id': layer_id, 'cursor': tuple(self.current_3d_pos),
            'mapping': vd.get('patient_plane'), 'shape': self.volume_hu.shape,
            'plane': vd['plane'], 'radius': vd['view'].brush_radius,
        }

    def _sync_committed_edit(self):
        record = self.study_document.series[self.active_series_uid]
        self.volume_mask, self.volume_conf = record.working_mask, record.confidence
        self.global_annotations = record.annotations
        self._update_organ_stats()
        self._refresh_layer_controls()
        self._refresh_series_link_status()
        self._sync_view_controls()
        if not self.recon_mode_active:
            self.update_display()

    def _paint_document(self, vid, points, is_erase):
        view = self.views[vid]['view']
        context = view.edit_context
        if context is None:  # 脚本/菜单直接调用也走相同已验证上下文。
            self._capture_edit_context(vid)
            context = view.edit_context
        if (context is None or context['document_id'] != self.study_document.document_id
                or context['series_uid'] != self.active_series_uid
                or context['plane'] != self.views[vid]['plane'] or not self._view_editable(self.views[vid])):
            return
        indices = mpr_geometry.stroke_voxels(points, context['radius'], context['mapping'],
                                             context['shape'], context['cursor'])
        if not len(indices):
            return
        self._remember_active_series()
        label = 0 if is_erase else int(self.cb_paint_target.currentData() or MANUAL_TRACK_LABEL)
        command = self.study_document.edit_mask(self.active_series_uid, indices, label,
                     layer_id=context['layer_id'], cursor=context['cursor'],
                     view_plane=context['plane'],
                     description='Erase' if is_erase else 'Paint')
        if command is not None:
            self.study_document.series[self.active_series_uid].active_layer_id = context['layer_id']
            self._stop_ai_for_manual_edit()
            self._sync_committed_edit()

    def _refresh_layer_controls(self):
        e = self.is_english
        doc = self.study_document
        self.cb_layers.blockSignals(True)
        self.cb_layers.clear()
        record = doc.series.get(self.active_series_uid) if doc is not None else None
        if record is not None:
            count = 0
            for layer in record.layers.values():
                if layer.readonly:
                    count += 1
                    name = f'Original AI {count}' if e else f'原始 AI {count}'
                elif layer.kind == 'lesion':
                    name = f'Lesion {layer.lesion_id[:8]}' if e else f'病灶 {layer.lesion_id[:8]}'
                else:
                    name = 'Working organs' if e else '器官工作结果'
                self.cb_layers.addItem(name, layer.layer_id)
            selected = self._display_layer_id or record.active_layer_id
            self.cb_layers.setCurrentIndex(self.cb_layers.findData(selected))
            layer = record.layers[selected]
            if layer.readonly:
                status = ('Read-only AI view. The Results tab uses the working layer.' if e else
                          '画面为只读原始 AI；结果页统计当前工作图层。')
            elif layer.provenance.get('modified'):
                status = 'Manually revised' if e else '已人工修订'
            elif layer.provenance.get('origin') == 'legacy-unknown':
                status = ('Imported working result; original AI unavailable.' if e else
                          '历史工作结果；原始 AI 不可用。')
            else:
                status = 'Working result' if e else '当前工作结果'
            self.lbl_layer_status.setText(status)
            self.btn_adopt_ai.setEnabled(layer.readonly)
        else:
            self.lbl_layer_status.setText(''); self.btn_adopt_ai.setEnabled(False)
        self.cb_layers.blockSignals(False)
        self.btn_adopt_ai.setText('Use this AI version as working result' if e else '采用此 AI 版本为工作结果')
        self.btn_new_lesion.setText('New lesion layer' if e else '新建病灶图层')
        self.btn_new_lesion.setEnabled(record is not None and record.source_binding is not None)
        self.btn_undo.setText('Undo last operation (Ctrl+Z)' if e else '撤销上一步 (Ctrl+Z)')
        self.btn_undo.setEnabled(doc is not None and bool(len(doc.history)))
        self._refresh_linked_lesion_controls()
        self._refresh_result_source()
        self._refresh_clear_target()

    def _linked_lesion_reference(self):
        doc = self.study_document
        sid = self.cb_reference_series.currentData()
        if (doc is None or self.recon_mode_active or self.compare_mode_active
                or self._display_layer_id is not None or sid not in doc.series
                or self.active_series_uid not in doc.series or sid == self.active_series_uid):
            raise ValueError('Choose another series and its working lesion layer')
        reference, target = doc.series[sid], doc.series[self.active_series_uid]
        layer = reference.layers[reference.active_layer_id]
        if (reference.source is None or target.source is None or not target.source_binding
                or layer.kind != 'lesion' or layer.readonly or not layer.lesion_id):
            raise ValueError('Reference series must have a connected working lesion')
        self._series_link_result(sid, self.active_series_uid)
        if any(other.lesion_id == layer.lesion_id for other in target.layers.values()):
            raise ValueError('This lesion already has a layer in the current series')
        return sid, layer

    def _refresh_linked_lesion_controls(self):
        if not hasattr(self, 'btn_link_lesion'):
            return
        e = self.is_english
        self.btn_link_lesion.setText('Link reference lesion' if e else '关联参考病灶')
        try:
            _, layer = self._linked_lesion_reference()
            tooltip = (f'Create an empty layer here for lesion {layer.lesion_id[:8]}; edit its range in this series.' if e
                       else f'为参考病灶 {layer.lesion_id[:8]} 在当前序列建立同编号空图层，范围在本序列独立标注。')
            enabled = True
        except (ValueError, KeyError, TypeError, AttributeError):
            tooltip = ('Select a working lesion in the reference series, then return here. Requires spatial correspondence and no existing layer for that lesion.' if e
                       else '先在参考序列选择病灶工作图层，再切回当前序列；需有可靠空间对应，且当前序列尚无该病灶图层。')
            enabled = False
        self.btn_link_lesion.setToolTip(tooltip)
        self.btn_link_lesion.setEnabled(enabled)

    def _link_reference_lesion(self):
        try:
            sid, reference = self._linked_lesion_reference()
            self._cancel_view_interactions()
            self._remember_active_series()
            layer_id = self.study_document.create_lesion_layer(self.active_series_uid,
                reference_series_uid=sid, reference_layer_id=reference.layer_id,
                cursor=tuple(self.current_3d_pos))
            self.study_document.series[self.active_series_uid].active_layer_id = layer_id
            self._display_layer_id = None
            self._sync_committed_edit()
        except (ValueError, KeyError) as exc:
            QMessageBox.information(self, 'Lesion not linked' if self.is_english else '未关联病灶', str(exc))

    def _new_lesion_layer(self):
        if self.study_document is None or self.recon_mode_active or self.compare_mode_active:
            return
        self._cancel_view_interactions()
        self._remember_active_series()
        record = self.study_document.series[self.active_series_uid]
        layer_id = self.study_document.create_lesion_layer(self.active_series_uid, cursor=tuple(self.current_3d_pos))
        record.active_layer_id = layer_id
        self._display_layer_id = None
        self._sync_committed_edit()

    def _on_layer_selected(self, index):
        if self.study_document is None or index < 0:
            return
        layer_id = self.cb_layers.itemData(index)
        record = self.study_document.series[self.active_series_uid]
        layer = record.layers.get(layer_id)
        if layer is None:
            return
        self._cancel_view_interactions()
        self._remember_active_series()
        if layer.readonly:
            self._display_layer_id = layer_id
        else:
            self._display_layer_id = None
            record.active_layer_id = layer_id
        self._sync_committed_edit()

    def _adopt_selected_ai(self):
        if self.study_document is None or self._display_layer_id is None:
            return
        self._cancel_view_interactions()
        self._remember_active_series()
        record = self.study_document.series[self.active_series_uid]
        original = record.layers[self._display_layer_id]
        target = 'working-organs' if original.kind == 'organ' else 'working-manual'
        self.study_document.adopt_ai_result(self.active_series_uid, self._display_layer_id,
                                             layer_id=target, cursor=tuple(self.current_3d_pos))
        record.active_layer_id = target
        self._display_layer_id = None
        self._stop_ai_for_manual_edit()
        self._sync_committed_edit()

    # =========================================================================
    # 分割蒙版编辑：3D 追踪 / 画笔 / 橡皮 / 撤销
    # =========================================================================
    def handle_3d_track_requested(self, vid, rect):
        """3D 连通域追踪：在当前 Axial 切片上框选 ROI，提取该区域的 HU 统计特征，
        然后在整个 3D 体积中找出 HU 分布相似的连通域，生成 3D 分割蒙版。

        算法原理：
          1. 计算 ROI 的 HU 中位数和标准差（中位数比均值更抗离群值）
          2. 在全体积中找出 HU 在 [med-1.5σ, med+1.5σ] 范围内的体素（类似区域增长）
          3. 对该 HU 范围内的体素做 3D 连通域标记
          4. 选取在 ROI 框内体素最多的连通域标签，即为目标结构
        """
        if (self.volume_hu is None or self.recon_mode_active or self.compare_mode_active
                or getattr(self, '_display_layer_id', None) is not None
                or not all((getattr(self, 'hu_calibrated', False),
                            getattr(self, 'canonical_orientation', False),
                            getattr(self, 'inplane_spacing_valid', False),
                            getattr(self, 'uniform_z_geometry_valid', False)))):
            return
        if self.views[vid]['plane'] != AXIAL:
            QMessageBox.information(self, "Info" if self.is_english else "提示",
                                    "3D tracking is only available on the axial plane."
                                    if self.is_english else "目前智能追踪仅支持在 Axial 进行。")
            return
        idx = self.current_3d_pos[0]
        x1, y1, x2, y2 = int(rect.left()), int(rect.top()), int(rect.right()), int(rect.bottom())
        h, w = self.volume_hu.shape[1], self.volume_hu.shape[2]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        p = QProgressDialog("Computing 3D..." if self.is_english else "正在计算 3D...", None, 0, 0, self)
        p.setWindowModality(Qt.WindowModal); p.show(); QApplication.processEvents()
        # 【失败必须可区分，且不得改动既有蒙版】原实现把整段包在 try/except: pass 里。
        # 空 ROI（np.median 对空数组返回 nan）、连通域计算抛异常、以及「ROI 内没有任何
        # 前景标签」三种结果全都表现为「点了没反应」，用户无法区分「没找到结构」与
        # 「算失败了」。现分成三条出口各给明确反馈；写蒙版的动作全部推迟到成功之后，
        # 故失败路径连 undo 都不压栈，既有 mask/confidence 逐位不变。
        tracked = None
        fail_msg = None
        e = self.is_english
        try:
            roi = self.volume_hu[idx, y1:y2, x1:x2]
            if roi.size == 0:
                fail_msg = ("The selected region is empty — draw a box with both width and "
                            "height inside the image." if e else
                            "框选区域为空——请在图像内画出同时具有宽和高的方框。")
            else:
                med, std = np.median(roi), np.std(roi)
                if not (np.isfinite(med) and np.isfinite(std)):
                    fail_msg = ("Could not compute HU statistics for the selected region."
                                if e else "无法对框选区域计算 HU 统计量。")
                else:
                    bv = ((self.volume_hu >= med - 1.5 * std)
                          & (self.volume_hu <= med + 1.5 * std))
                    lab, _ = ndimage.label(bv)
                    rl = lab[idx, y1:y2, x1:x2]
                    rl = rl[rl > 0]  # 过滤背景标签 0
                    if len(rl) == 0:
                        fail_msg = ("No connected structure was found in the selected region."
                                    if e else "框选区域内未找到连通结构。")
                    else:
                        # bincount 统计 ROI 内各标签出现次数，取最多的那个为目标
                        tracked = (lab == np.bincount(rl.flatten()).argmax())
        except Exception as exc:                      # 计算失败：如实报错，不动蒙版
            fail_msg = (f"3D tracking failed: {type(exc).__name__}: {exc}" if e else
                        f"3D 追踪计算失败：{type(exc).__name__}: {exc}")
        p.close()
        if fail_msg is not None:
            QMessageBox.warning(self, "3D Tracking" if e else "智能追踪", fail_msg)
            return                                    # 未写蒙版，不必刷新定量与显示
        if self.study_document is not None:
            self._remember_active_series()
            record = self.study_document.series[self.active_series_uid]
            layer_id = record.active_layer_id if record.layers[record.active_layer_id].kind == 'lesion' else 'working-manual'
            command = self.study_document.replace_mask(self.active_series_uid,
                np.where(tracked, MANUAL_TRACK_LABEL, 0).astype(np.uint8), None, layer_id=layer_id,
                cursor=tuple(self.current_3d_pos), view_plane=AXIAL, description='HU connected-component tracking')
            if command is not None:
                record.active_layer_id = layer_id
                self._stop_ai_for_manual_edit()
                self._sync_committed_edit()
            return
        # —— 以下为成功路径，此前不曾改动任何状态 ——
        self._stop_ai_for_manual_edit()
        if self.volume_mask is None:
            self.volume_mask = np.zeros(self.volume_hu.shape, dtype=np.uint8)
        self._push_volume_undo()
        # 【只动追踪层，不碰 AI 器官】旧实现在此处整卷赋值，一次追踪就把 ~100s 推理
        # 出的 24 类器官全部抹掉，且经 save_project 落盘后再也恢复不回来（实测：缓存
        # mask 里 100% 体素为 255，器官一个不剩）。现改为：先清掉上一次的追踪结果避免
        # 多次追踪累积，再写入本次；1-24 号器官标签原样保留。
        self.volume_mask[self.volume_mask == MANUAL_TRACK_LABEL] = 0
        self.volume_mask[tracked] = MANUAL_TRACK_LABEL
        # 追踪是用户画的，模型对它没有判断：把这些体素的置信度清成哨兵 0，
        # 否则定量表会拿「模型对该处原本器官的置信度」冒充追踪结果的置信度
        if getattr(self, 'volume_conf', None) is not None \
                and self.volume_conf.shape == self.volume_mask.shape:
            self.volume_conf[tracked] = 0
        self._update_organ_stats()  # 追踪已改写蒙版，定量面板同步刷新
        self.update_display()

    def handle_seg_paint(self, vid, points, is_erase):
        """分割手动修正：把画笔/橡皮轨迹写入当前 Axial 切片的 volume_mask。
        画笔补画为手动标注层(MANUAL_TRACK_LABEL)，橡皮把覆盖处清零（可擦除 AI 误分割）。
        用 QPainter 圆头粗线栅格化轨迹，与 handle_crop 的多边形栅格化同一套做法。
        """
        if self.volume_hu is None or self.recon_mode_active or self.compare_mode_active:
            return
        if getattr(self, 'study_document', None) is not None:
            self._paint_document(vid, points, is_erase)
            if not self.views[vid]['view'].is_drawing:
                self.views[vid]['view'].edit_context = None
            return
        if self.views[vid]['plane'] != AXIAL or not points:
            return
        if self.volume_mask is None:
            self.volume_mask = np.zeros(self.volume_hu.shape, dtype=np.uint8)
        z = self.current_3d_pos[0]
        h, w = self.volume_hu.shape[1], self.volume_hu.shape[2]
        r = max(1, self.views[vid]['view'].brush_radius)
        qi = QImage(w, h, QImage.Format_Grayscale8); qi.fill(Qt.black)
        painter = QPainter(qi)
        pen = QPen(Qt.white, r * 2); pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        if len(points) == 1:
            painter.drawPoint(QPointF(points[0][0], points[0][1]))
        else:
            path = QPainterPath(QPointF(points[0][0], points[0][1]))
            for px, py in points[1:]:
                path.lineTo(QPointF(px, py))
            painter.drawPath(path)
        painter.end()
        ma = np.array(qi.constBits(), dtype=np.uint8).reshape((h, qi.bytesPerLine()))[:, :w]
        brush = ma > 0
        if not brush.any():
            return
        self._stop_ai_for_manual_edit()
        self._push_mask_undo(z)   # 实际命中图像才接管 AI、记录编辑快照
        # 补画写入所选目标器官标签（修正计入该器官定量）；橡皮清零
        label = 0 if is_erase else int(self.cb_paint_target.currentData() or MANUAL_TRACK_LABEL)
        self.volume_mask[z][brush] = label
        # 手工改过的体素同样清成哨兵 0：其原值是模型对改动前那个标签的置信度
        if getattr(self, 'volume_conf', None) is not None \
                and self.volume_conf.shape == self.volume_mask.shape:
            self.volume_conf[z][brush] = 0
        self._update_organ_stats()
        self.update_display()

    _VOL_UNDO = 'VOL'         # 整卷快照的槽位标记（区别于逐切片的整数切片号）
    _VOL_UNDO_CLEAR = 'VOLC'  # 「清空蒙版」专用槽位——与上者分开保留，理由见 _push_volume_undo

    def _push_mask_undo(self, z):
        """把当前切片蒙版压入撤销栈（上限 20 步，含切片号以便精确回退）。

        置信度必须一起存：画笔与追踪会把改动体素的 conf 清成哨兵 0，而 quantify 用
        conf==0 剔除非模型体素。只还原 mask 的话，撤销后那个器官的 conf_cover 会
        永久 < 1——定量面板于是给一个 100% 来自模型的器官标上「模型判定 XX%」。
        撤销的语义是回到原状态，显示出来的数字也在内。
        """
        cf = None if self.volume_conf is None else self.volume_conf[z].copy()
        self._mask_undo.append((z, self.volume_mask[z].copy(), cf))
        if len(self._mask_undo) > 20:
            self._mask_undo.pop(0)

    def _push_volume_undo(self, slot=None, adopt=False):
        """整卷级操作（3D 追踪 / 清空蒙版）前存一份整卷快照。

        与逐切片快照走同一个栈，但同一槽位只保留最近一份：一份 (Z,H,W) uint8 在
        233×512² 下约 61MB，若像切片那样堆 20 份会吃掉 1.2GB。

        【清空单独占一个槽位】原先所有整卷操作共用一个槽位，于是「清空蒙版」存下的
        那份会被之后任意一次 3D 追踪顶掉——而清空的确认框刚刚写着「可用 Ctrl+Z
        还原蒙版」，被顶掉之后那 ~100 秒的推理产物就真的回不来了。清空是这里破坏性
        最大的一步，它的快照不该被一次普通编辑挤走。

        adopt=True 时直接接管传入的数组而不 copy：清空的调用方本来就要丢弃旧蒙版，
        移交给撤销栈是零成本的，不必为「保留两份整卷快照」多付一份内存。
        """
        if self.volume_mask is None:
            return
        slot = slot or self._VOL_UNDO
        cf = self.volume_conf
        if adopt:
            mask_snap, conf_snap = self.volume_mask, cf
        else:
            mask_snap, conf_snap = self.volume_mask.copy(), (None if cf is None else cf.copy())
        self._mask_undo = [e for e in self._mask_undo if e[0] != slot]
        self._mask_undo.append((slot, mask_snap, conf_snap))
        if len(self._mask_undo) > 20:
            self._mask_undo.pop(0)

    def _undo_mask_edit(self):
        """撤销最近一次分割编辑：整卷快照整卷还原，切片快照只还原该切片。"""
        if getattr(self, 'study_document', None) is not None:
            self._cancel_view_interactions()
            self._remember_active_series()
            try:
                command = self.study_document.undo()
            except ValueError as exc:
                QMessageBox.warning(self, 'Undo' if self.is_english else '撤销', str(exc))
                return
            if command is None:
                return
            self._stop_ai_for_manual_edit()
            self._mask_cache_clear_requested = False
            self._display_layer_id = None
            if command.series_uid != self.active_series_uid:
                self._activate_series(command.series_uid)
            record = self.study_document.series[command.series_uid]
            if command.layer_id is not None:
                record.active_layer_id = command.layer_id
            self.current_3d_pos = list(command.cursor)
            self.slider_slice.blockSignals(True)
            self.slider_slice.setValue(command.cursor[0])
            self.slider_slice.blockSignals(False)
            self._sync_committed_edit()
            if command.view_plane is not None:
                self.views[1]['cb_plane'].setCurrentIndex(command.view_plane)
            return
        if not self._mask_undo or self.volume_mask is None:
            return
        z, snap, conf_snap = self._mask_undo.pop()
        if z in (self._VOL_UNDO, self._VOL_UNDO_CLEAR):
            # 换病例后旧快照的形状可能与当前体积不符，形状不合则丢弃不还原
            if snap.shape != self.volume_mask.shape:
                return
            self.volume_mask = snap
            if z == self._VOL_UNDO_CLEAR:
                # 用户撤销了全局清空；后续保存应持久化恢复后的非零 mask，而非 empty intent。
                self._mask_cache_clear_requested = False
            # conf 与 mask 同源同快照：要么一起回退，要么都不动。形状不符时置 None
            # 而不是留着旧的——留着会让 quantify 拿错网格的哨兵去剔体素。
            if conf_snap is not None and conf_snap.shape == snap.shape:
                self.volume_conf = conf_snap
            elif conf_snap is None:
                self.volume_conf = None
        # z 越界保护：换病例后旧切片号可能超出新蒙版层数
        elif z < self.volume_mask.shape[0] and snap.shape == self.volume_mask[z].shape:
            self.volume_mask[z] = snap
            if (conf_snap is not None and self.volume_conf is not None
                    and conf_snap.shape == self.volume_conf[z].shape):
                self.volume_conf[z] = conf_snap
        else:
            return
        self._update_organ_stats()
        if not self.recon_mode_active:
            self.update_display()

    # =========================================================================
    # 截取工具（多边形 ROI 统计 + 可选导出）
    # =========================================================================
    def handle_crop_requested(self, vid, pts):
        """截取工具：对多边形 ROI 区域统计 HU 值，可选保存裁剪图像和 CSV 报告。

        步骤：
          1. 用 QPainter 将多边形栅格化为白色掩码图（白=ROI内，黑=ROI外）
          2. 将掩码转换为 NumPy 数组，提取 ROI 内的 HU 值
          3. 计算面积（像素数 × 像素间距²）和平均 HU
          4. 弹框确认，用户选择是否保存裁剪图像和 CSV 记录
        """
        if (self.recon_mode_active or self.compare_mode_active or self.views[vid]['plane'] != AXIAL
                or not getattr(self, 'hu_calibrated', False)
                or not getattr(self, 'inplane_spacing_valid', False)):
            return
        idx = self.current_3d_pos[0]
        ds = self.dicom_datasets[idx]
        hu = self.volume_hu[idx]
        # 列间距缺省回退到行间距而非 1.0：畸形 DICOM 的 PixelSpacing=[0.7, None] 下，
        # 写死 1.0 会让面积/体积整体偏大（0.7 时 +42.9%）。与 main.py 同一口径。
        _psr = self._dcm_float(ds, 'PixelSpacing', 0.0, idx=0)
        sp = (_psr, self._dcm_float(ds, 'PixelSpacing', 0.0, idx=1))
        h, w = hu.shape
        # 用 QPainter 将多边形光栅化为掩码图像
        mq = QImage(w, h, QImage.Format_Grayscale8); mq.fill(Qt.black)
        painter = QPainter(mq)
        painter.setBrush(Qt.white)
        painter.drawPolygon(QPolygonF([QPointF(p[0], p[1]) for p in pts]))
        painter.end()
        # 将 QImage 转换为 NumPy 掩码，bytesPerLine 可能因对齐而大于 w，需要裁剪
        ma = np.array(mq.constBits(), dtype=np.uint8).reshape((h, mq.bytesPerLine()))[:, :w].copy()
        bm = (ma > 0).astype(np.uint8)
        rh = hu[bm == 1]
        if len(rh) > 0:
            area = len(rh) * sp[0] * sp[1]
            _msg = (f"Area: {area:.2f} mm²\nMean: {np.mean(rh):.1f} HU\nSave?" if self.is_english
                    else f"面积: {area:.2f} mm²\n均值: {np.mean(rh):.1f} HU\n是否保存？")
            if QMessageBox.question(self, "Stats" if self.is_english else "统计", _msg) == QMessageBox.Yes:
                # 软组织窗归一化：-1250~250 HU 映射到 0~255（保存为 PNG）
                img = np.clip(hu, -1250, 250)
                img = ((img + 1250) / 1500 * 255).astype(np.uint8)
                fn = f"{self._export_tag()}_S{idx+1}_{datetime.now().strftime('%H%M%S')}.png"
                ed = getattr(self, 'export_dir',
                             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "Exported_Lesions"))
                os.makedirs(ed, exist_ok=True)
                default_path = self._unique_export_path(ed, fn)
                s_p, _ = QFileDialog.getSaveFileName(self, "Save", default_path, "PNG (*.png)")
                if s_p:
                    # img*bm：将 ROI 外的像素清零，保留病灶区域
                    saved = QImage((img * bm).data, w, h, w, QImage.Format_Grayscale8).copy().save(s_p)
                    if not saved:
                        QMessageBox.warning(self, "Export Failed" if self.is_english else "导出失败",
                                            "Could not save the PNG image. Check the destination."
                                            if self.is_english else "无法保存 PNG 图像，请检查目标目录与写入权限。")
                        return
                    try:
                        with open(os.path.join(os.path.dirname(s_p), "export_log.csv"), 'a',
                                  newline='', encoding='utf-8-sig') as f:
                            writer = csv.writer(f)
                            writer.writerow([os.path.basename(s_p), idx + 1, round(area, 2), round(np.mean(rh), 2)])
                    except OSError as e:
                        QMessageBox.warning(self, "Export Warning" if self.is_english else "导出警告",
                                            (f"Image saved but log write failed:\n{e}" if self.is_english
                                             else f"图像已保存，但日志写入失败：\n{e}"))

    # =========================================================================
    # 标注 CRUD
    # =========================================================================
    def handle_annotation_added(self, data):
        """将新增标注持久化到内存数据结构，并刷新显示。
        根据 chk_global_scope 决定标注归属：
          - 勾选"穿透所有切片"→ 存入 global_annotations['all']，所有切片可见
          - 未勾选 → 存入 global_annotations[当前切片索引]，仅该切片可见
        """
        if self.recon_mode_active or self.compare_mode_active or self._display_layer_id is not None:
            return
        if self.study_document is not None:
            src = self.sender()
            vid = next((key for key, vd in self.views.items() if vd['view'] is src), 1)
            vd = self.views[vid]
            if not self._view_editable(vd) or not self._valid_anno(data):
                return
            context = vd['view'].edit_context
            mapping = context['mapping'] if context else vd.get('patient_plane')
            cursor = context['cursor'] if context else tuple(self.current_3d_pos)
            reference = (self.chk_global_scope.isChecked() and vd['plane'] == AXIAL
                         and (self.canonical_orientation or mapping is None))
            data = mpr_geometry.bind_annotation(data, mapping, cursor, vd['plane'], reference_all=reference)
            tk = ('all' if reference else cursor[0]) if data['space']['kind'] == 'source' else 'objects'
            self._remember_active_series()
            annotations = deepcopy(self.global_annotations)
            annotations.setdefault(tk, []).append(data)
            self.study_document.edit_annotations(self.active_series_uid, annotations,
                    cursor=cursor, view_plane=vd['plane'], description='Add annotation')
            self._sync_committed_edit()
            return
        # 标注体系是【按 axial 层号】存、且 _render_annotations 只在 AXIAL 平面调用。
        # 在冠/矢状面画出来的标注会被存到当前 axial 层号下、按 axial 的 spacing 换算
        # 毫米、再画到另一个视图的不同解剖上——实测拖动中显示 60.0 mm、落库后变
        # 20.0 mm。与其静默产出错误数字，不如在入口拒绝并说明。
        src = self.sender()
        plane = next((vd['plane'] for vd in self.views.values()
                      if vd['view'] is src), AXIAL)
        if plane != AXIAL:
            if not getattr(self, '_warned_nonaxial_anno', False):
                self._warned_nonaxial_anno = True
                e = self.is_english
                QMessageBox.information(
                    self, "Axial only" if e else "仅支持横断面",
                    ("Annotations are stored and rendered per axial slice, so they can only be "
                     "drawn in an Axial view. The measurement you just made was discarded rather "
                     "than saved against the wrong slice. Switch a view to Axial and try again.")
                    if e else
                    ("标注按横断面（Axial）层号存储与绘制，因此只能在 Axial 视图中标注。"
                     "刚才那一笔已被丢弃，而不是错存到别的层上。请把某个视图切到 Axial 后重试。"))
            return
        tk = 'all' if self.chk_global_scope.isChecked() else self.current_3d_pos[0]
        if tk not in self.global_annotations:
            self.global_annotations[tk] = []
        # id 在整条链路上都被当作字符串：渲染时进 setToolTip（只收 str），删除时又从
        # toolTip 取回来比对（annotation_deleted 是 Signal(str)）。一个数字 id 会让
        # setToolTip 抛 TypeError 被渲染层的 except 吞掉——标注既画不出来也删不掉。
        # 故在入口一律规范成 str，而不是在渲染处打补丁。
        if isinstance(data, dict) and 'id' in data:
            data['id'] = str(data['id'])
        self.global_annotations[tk].append(data)
        self.update_display()

    def handle_annotation_deleted(self, aid):
        """按 UUID 从所有切片的标注列表中删除指定标注。
        遍历所有键是因为用户可能在不知情的情况下删除了一个全局标注。
        """
        if self.recon_mode_active or self.compare_mode_active or self._display_layer_id is not None:
            return
        identities = {str(value) for value in aid} if isinstance(aid, list) else {str(aid)}
        self._cancel_view_interactions()
        if self.study_document is not None:
            self._remember_active_series()
            annotations = {key: [a for a in values if a['id'] not in identities]
                           for key, values in self.global_annotations.items()}
            self.study_document.edit_annotations(self.active_series_uid, annotations,
                    cursor=tuple(self.current_3d_pos), description='Delete annotations')
            self._sync_committed_edit()
            return
        for k in self.global_annotations:
            self.global_annotations[k] = [a for a in self.global_annotations[k] if a['id'] not in identities]
        self.update_display()

    def _roi_change_callback(self, vdata, annotation):
        if self.study_document is None:
            return None
        document_id, series_uid = self.study_document.document_id, self.active_series_uid
        vid, plane = vdata['view'].view_id, vdata['plane']
        before = deepcopy(annotation)

        def changed(updated):
            if (self.study_document is None or self.study_document.document_id != document_id
                    or self.active_series_uid != series_uid or self.views[vid]['plane'] != plane
                    or not self._view_editable(vdata)):
                return
            self._remember_active_series()
            annotations = deepcopy(self.global_annotations)
            for objects in annotations.values():
                for index, original in enumerate(objects):
                    if original['id'] == before['id']:
                        if original != before:
                            return  # 晚到的释放事件不能覆盖后续编辑或 Undo。
                        if 'space' in original:
                            space = original['space']
                            updated = mpr_geometry.bind_annotation(updated,
                                vdata.get('patient_plane') if space['kind'] == 'patient' else None,
                                space['cursor'], plane, reference_all=space.get('reference_all', False))
                        objects[index] = updated
                        self.study_document.edit_annotations(series_uid, annotations,
                            cursor=tuple(self.current_3d_pos), view_plane=plane, description='Move/resize ROI')
                        self._sync_committed_edit()
                        return
        return changed

    def clear_mask_and_annotations(self):
        """清空【当前切片】的标注，并把【整卷】分割蒙版重置为全零。

        两者粒度本就不同（标注按切片、蒙版整卷），旧实现对此不置一词，用户无从
        得知一次点击会波及全部切片；蒙版中若含 AI 器官，清掉意味着 ~100s 的推理
        作废且不可逆。故此处：先算清代价并要求确认，再压入整卷快照（Ctrl+Z 可还原）。
        无可清时直接返回，不弹框骚扰、也不改动任何状态。
        """
        if self.study_document is not None:
            if self.recon_mode_active or self.compare_mode_active or self._display_layer_id is not None:
                return
            if not self.volume_mask.any() and not any(self.global_annotations.values()):
                return
            answer = QMessageBox.question(self, 'Clear working result' if self.is_english else '清空工作结果',
                'Clear the active working mask on all slices and this series\' annotations? Ctrl+Z restores both.'
                if self.is_english else '清空当前工作图层的全部切片及本序列普通标注？Ctrl+Z 可一起恢复。',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            self._cancel_view_interactions()
            self._remember_active_series()
            self.study_document.replace_mask(self.active_series_uid, np.zeros_like(self.volume_mask), None,
                annotations={'all': []}, cursor=tuple(self.current_3d_pos), description='Clear working result')
            self._invalidate_running_ai()
            self._mask_cache_clear_requested = True
            self._sync_committed_edit()
            return
        idx = self.current_3d_pos[0]
        n_anno = len(self.global_annotations.get(idx, []))
        has_mask = self.volume_mask is not None and bool(self.volume_mask.any())
        if not n_anno and not has_mask:
            return
        if has_mask:
            organ = (self.volume_mask > 0) & (self.volume_mask != MANUAL_TRACK_LABEL)
            n_organ = int(np.unique(self.volume_mask[organ]).size)
            zs = int(self.volume_mask.shape[0])
            if self.is_english:
                msg = (f"This clears {n_anno} annotation(s) on the current slice AND the "
                       f"segmentation mask on ALL {zs} slices.")
                if n_organ:
                    msg += (f"\n\n{n_organ} AI-segmented organ(s) will be lost; "
                            f"re-running inference takes about 100 s on CPU.")
                msg += "\n\nCtrl+Z restores the mask."
            else:
                msg = f"将清除当前切片的 {n_anno} 条标注，以及【全部 {zs} 层】的分割蒙版。"
                if n_organ:
                    msg += f"\n\n其中含 AI 分割的 {n_organ} 个器官，清除后需重新推理（CPU 约 100 秒）。"
                msg += "\n\n可用 Ctrl+Z 还原蒙版。"
            if QMessageBox.question(self, "Confirm" if self.is_english else "确认清空", msg,
                                    QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No) != QMessageBox.Yes:
                return
            # 用专属槽位，免得之后一次 3D 追踪把它顶掉——确认框刚承诺过 Ctrl+Z 可还原。
            # adopt=True：旧蒙版与旧 conf 本来就要被丢弃，移交给撤销栈是零成本的。
            self._invalidate_running_ai()  # 先作废旧代次，避免后台结果在清空后复活
            self._push_volume_undo(slot=self._VOL_UNDO_CLEAR, adopt=True)
            self.volume_mask = np.zeros(self.volume_hu.shape, dtype=np.uint8)
            self.volume_conf = None
            self._mask_cache_clear_requested = True
        if idx in self.global_annotations:
            self.global_annotations[idx] = []
        self._update_organ_stats()  # 蒙版已清，定量面板同步清空
        if not self.recon_mode_active:
            self.update_display()

    def _refresh_clear_target(self):
        """展示实际清空目标；隐藏视图和只读/投影状态不提供清空入口。"""
        if not hasattr(self, 'cb_clear_view') or not hasattr(self, 'btn_clear_slice'):
            return
        e = self.is_english
        def plane_name(vd):
            if vd.get('patient_plane') is not None or self.canonical_orientation:
                return ('Axial', 'Coronal', 'Sagittal')[vd['plane']]
            return 'Source voxel plane' if e else '原始体素平面'
        for index in range(self.cb_clear_view.count()):
            vid = self.cb_clear_view.itemData(index); vd = self.views[vid]
            hidden = vd['container'].isHidden()
            text = f'V{vid} · {plane_name(vd)}' + ((' · hidden' if e else ' · 未显示') if hidden else '')
            self.cb_clear_view.setItemText(index, text)
            self.cb_clear_view.model().item(index).setEnabled(not hidden)
        vid = self.cb_clear_view.currentData(); vd = self.views.get(vid)
        available = (vd is not None and not vd['container'].isHidden()
                     and self.study_document is not None and self._view_editable(vd))
        self.btn_clear_slice.setEnabled(available)
        if not available:
            self.lbl_clear_target.setText('Choose a visible, editable single-slice view.' if e
                                          else '请选择已显示、可编辑的单层视图。')
            return
        layer = self.cb_layers.currentText()
        self.lbl_clear_target.setText(f'Target: V{vid} · {plane_name(vd)}\nLayer: {layer}\nOnly this displayed plane; Undo available.' if e
            else f'目标：V{vid} · {plane_name(vd)}\n图层：{layer}\n仅清空此视图当前面，可撤销。')

    def _refresh_result_source(self):
        if not hasattr(self, 'lbl_stats_source'):
            return
        e = self.is_english
        doc = self.study_document
        record = doc.series.get(self.active_series_uid) if doc else None
        if record is None:
            text = 'No connected working result.' if e else '尚无已连接的工作结果。'
        else:
            index = self.cb_layers.findData(record.active_layer_id)
            working = self.cb_layers.itemText(index)
            display = self.cb_layers.currentText()
            text = (f'Image: {display}\nStatistics / CSV / 3D: {working}' if e
                    else f'画面：{display}\n统计 / CSV / 三维：{working}')
        self.lbl_stats_source.setText(text)

    def _refresh_workspace_state(self):
        if not hasattr(self, 'primary_view_stack'):
            return
        e = self.is_english
        empty = self.volume_hu is None and not (self.recon_mode_active and self._phantom_img is not None)
        self.primary_view_stack.setCurrentIndex(1 if empty else 0)
        doc = self.study_document
        offline = empty and doc is not None and bool(doc.series)
        self.lbl_empty_title.setText(('Project opened — connect source images' if e else '工程已打开，请连接原始影像')
                                    if offline else ('Start with an image or project' if e else '从影像或已有工程开始'))
        detail = ((f'Annotations are retained. {len(doc.series)} series await their matching DICOM source.' if e
                   else f'工程标注已保留，{len(doc.series)} 个序列等待连接匹配的原始 DICOM。') if offline
                  else ('Load a CT / MRI DICOM folder, or open a saved annotation project.' if e
                        else '加载 CT / MRI DICOM 目录，或继续已有的标注工程。'))
        self.lbl_empty_detail.setText(detail)
        self.btn_empty_import.setText(('Connect DICOM Source' if e else '连接原始 DICOM') if offline
                                      else ('Load DICOM Folder' if e else '加载 DICOM 目录'))
        self.btn_empty_open.setText('Open Project' if e else '打开工程')

    def clear_current_slice(self, vid=None):
        vid = vid or getattr(self, '_last_edit_vid', 1)
        vd = self.views[vid]
        if self.study_document is None or not self._view_editable(vd):
            return
        self._cancel_view_interactions()
        mapping = vd.get('patient_plane')
        mask = self.volume_mask.copy()
        confidence = None if self.volume_conf is None else self.volume_conf.copy()
        if mapping is not None:
            coordinates = mapping.source_coordinates().reshape(3, -1).T
            valid = np.all((coordinates >= -.5) & (coordinates < np.asarray(mask.shape) - .5), axis=1)
            indices = tuple(np.floor(coordinates[valid] + .5).astype(int).T)
        else:
            indices = (int(self.current_3d_pos[0]), slice(None), slice(None))
        mask[indices] = 0
        if confidence is not None:
            confidence[indices] = 0
        annotations = deepcopy(self.global_annotations)
        if vd['plane'] == AXIAL and (mapping is None or self.canonical_orientation):
            annotations.pop(self.current_3d_pos[0], None)
        for key, objects in annotations.items():
            annotations[key] = [annotation for annotation in objects
                if not (annotation.get('space', {}).get('kind') == 'patient'
                        and annotation['space']['plane'] == vd['plane']
                        and mpr_geometry.project_annotation(annotation, mapping)['coplanar'])]
        if np.array_equal(mask, self.volume_mask) and annotations == self.global_annotations:
            return
        self._remember_active_series()
        self.study_document.replace_mask(self.active_series_uid, mask, confidence, annotations=annotations,
            cursor=tuple(self.current_3d_pos), view_plane=vd['plane'], description='Clear current plane')
        self._stop_ai_for_manual_edit()
        self._sync_committed_edit()

    # =========================================================================
    # 标注 / 蒙版持久化
    # =========================================================================
    @staticmethod
    def _valid_anno(a):
        """校验单条标注结构完整。用于加载 JSON 时过滤畸形/旧版本/被篡改的条目——
        _render_annotations 会在每次刷新时硬取 type/p1/p2/points/rect，缺字段或类型
        不符会让整个显示刷新崩溃（等于阅片被卡死），故在入口就挡掉不合规条目。"""
        if not isinstance(a, dict) or 'id' not in a:
            return False
        def _pair(p):
            return isinstance(p, (list, tuple)) and len(p) >= 2 \
                and all(isinstance(c, (int, float)) and math.isfinite(c) for c in p[:2])
        t = a.get('type')
        if t == 'ruler':
            return _pair(a.get('p1')) and _pair(a.get('p2'))
        if t == 'path':
            pts = a.get('points')
            return isinstance(pts, (list, tuple)) and len(pts) >= 1 and all(_pair(p) for p in pts)
        if t == 'roi':
            r = a.get('rect')
            return isinstance(r, (list, tuple)) and len(r) == 4 \
                and all(isinstance(c, (int, float)) and math.isfinite(c) for c in r)
        return False

    def _load_annotations_json(self, pid):
        """尝试加载同 PatientID 命名的注解 JSON 文件，恢复历史标注。
        不存在时跳过；无法转换的条目明确报告，原文件仅供读取。"""
        ed = getattr(self, 'persistence_dir',
                     os.path.join(os.path.dirname(os.path.abspath(__file__)), "Exported_Lesions"))
        af = os.path.join(ed, f"{self._safe_name(pid)}_annotations.json")
        if not os.path.exists(af):
            return
        try:
            with open(af, encoding='utf-8') as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError('Expected an annotation object')
            meta = raw.pop('__meta__', None)
            saved_uid = (meta or {}).get('series_uid', '') if isinstance(meta, dict) else ''
            saved_fingerprint = ((meta or {}).get('geometry_fingerprint', '')
                                 if isinstance(meta, dict) else '')
            cur_uid = self._current_series_uid()
            cur_fingerprint = self._current_geometry_fingerprint()
            if (not saved_uid or not cur_uid or saved_uid != cur_uid
                    or not saved_fingerprint or saved_fingerprint != cur_fingerprint):
                # 明确是另一序列：拒绝。标注坐标按切片号存，套到同形状的另一序列上
                # 会落在完全不同的解剖上，而测距/ROI 会照样给出数字。
                print("标注文件缺少或不匹配 geometry/order fingerprint，"
                      f"已跳过加载：{af}")
                e = self.is_english
                QMessageBox.information(
                    self, "Annotations not loaded" if e else "标注未加载",
                    ("The saved annotations lack a matching geometry/order fingerprint and "
                     "were not loaded; their slice indices cannot be proven safe. The file "
                     "was left untouched.") if e else
                    ("已保存标注缺少匹配的 geometry/order fingerprint，无法证明切片号对应"
                     "关系，故未加载；原文件保留在磁盘上，未改动。"))
                return
            skipped = 0; seen = set()
            for k, v in raw.items():
                # JSON 键只能是字符串，数字键需要转回 int
                key = int(k) if isinstance(k, str) and k.isdigit() else k
                if key != 'all' and (type(key) is not int or not 0 <= key < len(self.dicom_datasets)):
                    skipped += len(v) if isinstance(v, list) else 1
                    continue
                annos = v if isinstance(v, list) else []
                skipped += int(not isinstance(v, list))
                valid = []
                for a in annos:
                    if not self._valid_anno(a) or str(a['id']) in seen:
                        skipped += 1; continue
                    a['id'] = str(a['id']); seen.add(a['id']); valid.append(a)
                self.global_annotations[key] = valid
            if skipped:
                QMessageBox.information(self, 'Partial annotation import' if self.is_english else '部分旧标注未迁移',
                    (f'{skipped} invalid or unsupported entries were not imported. Original file retained:\n{af}'
                     if self.is_english else f'{skipped} 条畸形或不支持的条目未能迁移；有效条目已读取，原文件保留：\n{af}'))
        except Exception as e:
            print(f"Warning: failed to load annotations from {af}: {e}")
            QMessageBox.information(self, 'Annotations not loaded' if self.is_english else '旧标注未加载',
                f'{e}\n' + ('Original file retained: ' if self.is_english else '原文件保留：') + af)

    def _current_series_uid(self):
        """当前序列的 SeriesInstanceUID；无数据或畸形 DICOM 缺该标签时返回 ''。"""
        if not self.dicom_datasets:
            return ''
        return str(getattr(self.dicom_datasets[0], 'SeriesInstanceUID', '') or '')

    def _current_geometry_fingerprint(self):
        """当前有序 volume 的稳定 geometry/order SHA-256；无法证明时为空。"""
        if self.volume_hu is None:
            return ''
        return series_fingerprint(self.dicom_datasets, self.volume_hu.shape)

    def _load_saved_mask(self, pid):
        """尝试加载上次保存的 AI 分割标签图(.npz)。自动恢复要求 SeriesInstanceUID、
        mask/volume shape、geometry/order fingerprint 与 AI 面内轴向契约四者均匹配；legacy cache 缺少
        fingerprint 时 fail closed。判定分在两个纯函数：mask_axis_contract_ok 与 mask_cache_matches（均无 Qt，可独立
        单测），避免同一患者的随访/复扫、切片重排或几何变化静默复用错误蒙版。
        """
        ed = getattr(self, 'persistence_dir',
                     os.path.join(os.path.dirname(os.path.abspath(__file__)), "Exported_Lesions"))
        fp = os.path.join(ed, f"{self._safe_name(pid)}_mask.npz")
        if not os.path.exists(fp):
            return False
        try:
            with np.load(fp, allow_pickle=False) as z:
                m = z['mask']
                saved_uid = str(z['series_uid'].item()) if 'series_uid' in z.files else ''
                saved_fingerprint = (str(z['geometry_fingerprint'].item())
                                     if 'geometry_fingerprint' in z.files else '')
                saved_contract = (str(z['axis_contract'].item()) if 'axis_contract' in z.files else '')
            if m.dtype != np.uint8:
                raise ValueError('Legacy labels must be uint8; refusing a lossy conversion')
            ok, why = mask_axis_contract_ok(saved_contract)
            if ok:
                ok, why = mask_cache_matches(saved_uid, m.shape, saved_fingerprint,
                                             self._current_series_uid(), self.volume_hu.shape,
                                             self._current_geometry_fingerprint())
            if not ok:
                print(f"跳过磁盘缓存的分割蒙版：{why}；将重新运行 AI 分割。")
                return False
            self.volume_mask = m
            if self.study_document is not None:
                record = self.study_document.series[self.active_series_uid]
                digest = hashlib.sha256()
                with open(fp, 'rb') as stream:
                    while block := stream.read(1024**2):
                        digest.update(block)
                record.layers[record.active_layer_id].provenance = {
                    'origin': 'legacy-unknown', 'modified': False,
                    'import_sha256': digest.hexdigest(), 'imported_at': datetime.now().astimezone().isoformat(),
                }
            self._mask_cache_clear_requested = False
            return True
        except Exception as e:
            print(f"Warning: failed to load saved mask: {e}")
        return False

    def _init_project_storage(self, project_dir, autosave):
        self.project_dir = os.path.abspath(project_dir) if project_dir else None
        self._project_settings = QSettings('MedicalImagingWorkstation', 'AnnotationProjects')
        self._autosave_enabled = bool(autosave)
        self._last_save_error = ''
        self._last_saved_at = ''
        self._save_worker = None
        self._save_pending = False
        self._save_generation = 0
        self._save_sync_wait = False
        self._leaving_document = False
        self._registration_worker = None
        self._registration_generation = 0
        self._autosave_idle = QTimer(self); self._autosave_idle.setSingleShot(True)
        self._autosave_idle.setInterval(2000)
        self._autosave_max = QTimer(self); self._autosave_max.setSingleShot(True)
        self._autosave_max.setInterval(30000)
        self._autosave_idle.timeout.connect(self._start_project_save)
        self._autosave_max.timeout.connect(self._start_project_save)

    def _bind_project_document(self, document):
        if self.study_document is not document:
            if self.study_document is not None:
                self.study_document.on_change = None
            self._save_generation += 1
        self.study_document = document
        document.on_change = self._on_document_changed
        self._last_save_error = ''
        self._last_saved_at = document.saved_at
        self._refresh_registration_controls()

    def _on_document_changed(self, document):
        if document is not self.study_document:
            return
        self._refresh_project_status()
        if (not self._autosave_enabled or self._leaving_document
                or document.revision == document.saved_revision
                or not document.study_uid or not any(r.source_binding for r in document.series.values())):
            return
        self._autosave_idle.start()
        if not self._autosave_max.isActive():
            self._autosave_max.start()

    def _start_project_save(self):
        self._autosave_idle.stop(); self._autosave_max.stop()
        doc = self.study_document
        if doc is None:
            return False
        if self._save_worker is not None:
            self._save_pending = True
            return True
        try:
            self._remember_active_series()
            snapshot = capture_project_snapshot(doc)
            path = doc.project_path or self._project_path_for_study(doc.study_uid)
            worker = ProjectSaveWorker(snapshot, path, self._save_generation, self)
            self._save_worker = worker; self._save_pending = False
            self._last_save_error = ''
            worker.finished.connect(self._on_save_worker_finished)
            worker.start()
            self._refresh_project_status()
            return True
        except (OSError, ValueError, TypeError, AttributeError, MemoryError) as exc:
            self._last_save_error = str(exc); self._save_pending = False
            self._refresh_project_status()
            return False

    def _on_save_worker_finished(self):
        worker = self.sender()
        if worker is not self._save_worker:
            return
        self._save_worker = None
        doc = self.study_document
        current = (doc is not None and worker.generation == self._save_generation
                   and worker.snapshot.manifest['document_id'] == doc.document_id)
        pending = self._save_pending; self._save_pending = False
        if current:
            if worker.error is not None:
                self._last_save_error = worker.error
            elif worker.receipt is not None:
                receipt = worker.receipt
                doc.project_path = receipt.path
                doc.saved_revision = receipt.revision
                doc.saved_at = receipt.saved_at
                self._last_saved_at = receipt.saved_at; self._last_save_error = ''
                if doc.revision == receipt.revision:
                    self._mask_cache_clear_requested = False
                    self._autosave_idle.stop(); self._autosave_max.stop()
        self._refresh_project_status()
        worker.deleteLater()
        if pending and doc is not None and (not current or not worker.error) and not self._save_sync_wait:
            self._start_project_save()

    def _wait_project_worker(self):
        worker = self._save_worker
        if worker is not None:
            loop = QEventLoop(self)
            worker.finished.connect(loop.quit)
            loop.exec()

    def _save_project_sync(self):
        doc = self.study_document
        if doc is None:
            self._last_save_error = 'No bound project is loaded'
            return False
        self._save_sync_wait = True
        central = self.centralWidget(); was_enabled = central.isEnabled()
        central.setEnabled(False)
        try:
            self._wait_project_worker()
            self._save_pending = False
            if not self._start_project_save():
                return False
            self._wait_project_worker()
            return not self._last_save_error and doc.saved_revision == doc.revision
        finally:
            self._save_sync_wait = False
            central.setEnabled(was_enabled)

    def _choose_save_failure(self):
        e = self.is_english
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle('Unsaved project' if e else '工程尚未保存')
        box.setText(('Saving failed. Your current work is retained.\n' if e else '保存失败，当前工作仍保留。\n')
                    + self._last_save_error)
        actions = {}
        for key, label in (('retry', 'Retry' if e else '重试'),
                           ('directory', 'Change location' if e else '更换保存位置'),
                           ('cancel', 'Stay here' if e else '取消离开'),
                           ('discard', 'Discard unsaved changes' if e else '放弃未保存修改')):
            role = QMessageBox.RejectRole if key == 'cancel' else QMessageBox.DestructiveRole if key == 'discard' else QMessageBox.ActionRole
            actions[box.addButton(label, role)] = key
        box.exec()
        return actions.get(box.clickedButton(), 'cancel')

    def _prepare_document_leave(self):
        if self._leaving_document or self._save_sync_wait:
            return False
        self._leaving_document = True
        self._autosave_idle.stop(); self._autosave_max.stop()
        self._stop_cine(); self._cancel_view_interactions(); self._invalidate_running_ai()
        self._cancel_series_registration()
        try:
            worker = self._registration_worker
            if worker is not None:
                central = self.centralWidget(); enabled = central.isEnabled(); central.setEnabled(False)
                try:
                    loop = QEventLoop(self); worker.finished.connect(loop.quit); loop.exec()
                finally:
                    central.setEnabled(enabled)
            self._remember_active_series()
            doc = self.study_document
            if not self._autosave_enabled or doc is None:
                self._save_sync_wait = True
                try:
                    self._wait_project_worker()
                finally:
                    self._save_sync_wait = False
                self._save_pending = False
                return True
            # 纯阅片、所有来源都无法绑定时没有可编辑内容，不强求一个无法验证的工程。
            if not doc.study_uid or not any(r.source_binding for r in doc.series.values()):
                return True
            while doc.revision != doc.saved_revision or self._save_worker is not None:
                if self._save_project_sync():
                    break
                action = self._choose_save_failure()
                if action == 'discard':
                    return True
                if action == 'cancel':
                    return False
                if action == 'directory' and not self.choose_project_directory():
                    return False
            return True
        finally:
            self._leaving_document = False

    def _project_root(self):
        if self.project_dir:
            return self.project_dir
        legacy_default = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Exported_Lesions')
        if self.persistence_dir != legacy_default:
            # 嵌入/测试重定向旧读取目录时，新工程也留在该隔离目录内。
            return os.path.join(self.persistence_dir, 'projects')
        return str(self._project_settings.value('directory',
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Annotation_Projects')))

    def _project_path_for_study(self, study_uid):
        return os.path.join(self._project_root(), hashlib.sha256(study_uid.encode()).hexdigest() + '.miwproj')

    def _refresh_project_status(self):
        if not hasattr(self, 'lbl_project_status'):
            return
        doc = self.study_document
        e = self.is_english
        path = doc.project_path if doc and doc.project_path else self._project_path_for_study(doc.study_uid) if doc else self._project_root()
        if self._last_save_error:
            status = ('Save failed: ' if e else '保存失败：') + self._last_save_error
        elif doc is None:
            status = 'No project loaded' if e else '尚未载入工程'
        elif not any(record.source_binding for record in doc.series.values()):
            status = 'Read-only: source identity unavailable' if e else '仅阅片：缺少来源身份，无法保存工程'
        elif self._save_worker is not None:
            status = 'Saving...' if e else '保存中…'
        elif doc.revision != doc.saved_revision:
            status = 'Unsaved changes' if e else '有未保存修改'
        else:
            stamp = datetime.fromisoformat(self._last_saved_at).astimezone().strftime('%H:%M:%S') if self._last_saved_at else ''
            status = ('Saved ' if e else '已保存 ') + stamp
        self.lbl_project_status.setText(status)
        self.lbl_project_status.setStyleSheet('color: #F0AB91;' if self._last_save_error else '')
        self._refresh_workspace_state()
        unbound = sum(not record.source_binding for record in doc.series.values()) if doc else 0
        note = (f'\n{unbound} unbound read-only series are excluded from the project.' if e
                else f'\n{unbound} 个无稳定来源身份的序列仅供阅片，不纳入工程。') if unbound else ''
        if self._last_saved_at:
            note += ('\nLast successful save: ' if e else '\n最后成功保存：') + self._last_saved_at
        self.lbl_project_status.setToolTip(
            path + ('\n.miwproj: ZIP with JSON metadata/history, NPZ labels and CSV summary; source DICOM required for editing.'
                    if e else '\n.miwproj 工程包：JSON 元数据与历史、NPZ 标注、CSV 摘要；编辑仍需匹配的原始 DICOM。') + note)

    def _read_project_candidate(self, path):
        try:
            return load_project_snapshot(path)
        except HistoryRecoveryRequired as exc:
            answer = QMessageBox.question(self, 'Recover annotations' if self.is_english else '恢复标注副本',
                (f'{exc}\nRestore verified annotations into a new project with no old Undo history? The original stays protected.'
                 if self.is_english else f'{exc}\n是否将已验证标注恢复为独立工程副本？旧撤销历史不可用，原件保持保护。'),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                try:
                    return load_project_snapshot(path, recover_history=True)
                except ProjectError as failure:
                    exc = failure
            else:
                return None
            QMessageBox.warning(self, 'Open failed' if self.is_english else '打开失败', str(exc))
        except ProjectError as exc:
            QMessageBox.warning(self, 'Open failed' if self.is_english else '打开失败', str(exc))
        return None

    def choose_project_directory(self):
        path = QFileDialog.getExistingDirectory(self, 'Save directory' if self.is_english else '保存目录',
                                                 self._project_root())
        if not path:
            return False
        self.project_dir = os.path.abspath(path)
        self._project_settings.setValue('directory', self.project_dir)
        if self.study_document:
            doc = self.study_document
            # 恢复副本保留独立文件名，不能因更换目录退回默认 Study 文件名。
            name = os.path.basename(doc.project_path) if doc.project_path else os.path.basename(self._project_path_for_study(doc.study_uid))
            target = os.path.join(self.project_dir, name)
            # 选目录只授权保存到该目录，不意味着覆盖那里另一份同名工程。
            if os.path.exists(target) and os.path.realpath(target) != os.path.realpath(doc.project_path or ''):
                stem = os.path.splitext(name)[0]
                while os.path.exists(target):
                    target = os.path.join(self.project_dir, f'{stem}_{uuid.uuid4().hex}.miwproj')
            doc.project_path = target
            doc.saved_revision = -1
            # 旧 worker 仍可完成旧路径，但其回执不得将用户新选路径改回去。
            self._save_generation += 1
            self._save_pending = self._save_worker is not None
            self._on_document_changed(doc)
        self._refresh_project_status()
        return True

    def show_project_directory(self):
        doc = self.study_document
        path = os.path.dirname(doc.project_path) if doc and doc.project_path else self._project_root()
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_project(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Open project' if self.is_english else '打开工程',
                                                 self._project_root(), 'MIW Project (*.miwproj)')
        if not path:
            return False
        candidate = self._read_project_candidate(path)
        if candidate is None:
            return False
        current = self.study_document
        if current and current.study_uid == candidate.study_uid:
            try:
                candidate.attach_sources([record.source for record in current.series.values() if record.source])
            except ValueError as exc:
                QMessageBox.warning(self, 'Source mismatch' if self.is_english else '来源不匹配', str(exc))
                return False
        if not self._prepare_document_leave():
            return False
        # 关闭旧工程的保存可能刚更新了本次要打开的同一路径；不能装回保存前的旧候选。
        if (current is not None and current.project_path
                and os.path.abspath(path) == os.path.abspath(current.project_path)
                and current.saved_revision == current.revision):
            candidate = self._read_project_candidate(path)
            if candidate is None:
                return False
            try:
                candidate.attach_sources([record.source for record in current.series.values() if record.source])
            except ValueError as exc:
                QMessageBox.warning(self, 'Source mismatch' if self.is_english else '来源不匹配', str(exc))
                return False
        self._remember_active_series()
        self._cancel_view_interactions(); self._invalidate_running_ai(); self._stop_cine()
        if self.compare_mode_active:
            self._exit_compare_mode()
        self._invalidate_recon_results()
        self._bind_project_document(candidate); self.active_series_uid = None
        self._refresh_series_selector()
        connected = [sid for sid, record in candidate.series.items() if record.source]
        if connected:
            self._activate_series(connected[0])
        else:
            self._active_source = None; self.dicom_datasets = []
            self.volume_hu = self.volume_mask = self.volume_conf = None
            self.global_annotations = {'all': []}; self._display_layer_id = None
            # 离线工程仍保留完整文档；只撤下上一活动序列的能力、AI与定量显示。
            self.hu_calibrated = self.canonical_orientation = False
            self.inplane_spacing_valid = self.uniform_z_geometry_valid = False
            self.series_geometry = SeriesGeometry(False, False, False, False, None, None, None)
            self._ct_preview_scale = None
            self._ai_state = 'standby'; self._ai_time_ms = 0.0
            self._ai_fallback = False; self._ai_resampled = None
            self._hidden_organs.clear(); self._mask_cache_clear_requested = False
            self.lbl_ai_status.setStyleSheet('color: #8B949E; font-weight: bold;')
            self.lbl_ai_status.setText(self._standby_text())
            self._update_organ_stats(); self._update_legend([])
            self._refresh_patient_info(); self.lbl_hud.setText(''); self.lbl_hu_value.setText('')
            self._refresh_layer_controls()
            self._refresh_registration_controls()
            for vd in self.views.values():
                view = vd['view']; view.cancel_interaction()
                view.set_image(QPixmap()); view.mask_item.setPixmap(QPixmap())
                vd['patient_plane'] = None
                view.clear_annotations()
                view.vline.hide(); view.hline.hide()
                view.overlay_lines = {}; view.orient_labels = {}; view.viewport().update()
            self._sync_view_controls(); self._sync_matrix_buttons()
            self.update_display()
            if self.recon_mode_active and self._phantom_img is not None:
                # 模体是独立重建源；离线接入不能保留可运行状态却把它的画面清成黑屏。
                self.display_numpy_image(1, self._phantom_img)
                self.set_view_title(1, 'V1 [Phantom · known truth]' if self.is_english else 'V1 [模体 · 真值已知]')
            self._refresh_recon_empty_states()
        self._last_save_error = ''; self._last_saved_at = candidate.saved_at
        self._refresh_project_status()
        self._on_document_changed(candidate)
        return True

    def save_project(self):
        """保存整个检查的单个工程包；旧 Exported_Lesions 仅供兼容读取。"""
        try:
            doc = self.study_document
            if doc is None:
                raise ProjectError('No bound project is loaded')
            if not self._save_project_sync():
                raise ProjectError(self._last_save_error or 'New changes are still pending')
            if self.anonymize:
                QMessageBox.warning(self, 'Internal project identifiers' if self.is_english else '内部工程仍含标识',
                    'The project retains source series identifiers; display De-ID does not remove them.'
                    if self.is_english else '工程保留来源序列标识；屏幕脱敏开关不会移除这些内部标识。')
            self._refresh_project_status()
            return True
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self._last_save_error = str(exc); self._refresh_project_status()
            QMessageBox.warning(self, 'Save failed' if self.is_english else '保存失败', str(exc))
            return False

    # =========================================================================
    # 器官定量 / 图例
    # =========================================================================
    def _compute_organ_stats(self):
        """器官定量薄包装：读取 self 的体积/蒙版/spacing 后调用纯函数
        quantify.compute_organ_stats（无 Qt，可独立单测）。返回按体积降序的列表。"""
        if (self.volume_mask is None or self.volume_hu is None or not self.dicom_datasets
                or not all((getattr(self, 'hu_calibrated', False),
                            getattr(self, 'canonical_orientation', False),
                            getattr(self, 'inplane_spacing_valid', False),
                            getattr(self, 'uniform_z_geometry_valid', False)))):
            return []
        ds = self.dicom_datasets[0]
        _psr = self._dcm_float(ds, 'PixelSpacing', 0.0, idx=0)
        spacing = (_psr, self._dcm_float(ds, 'PixelSpacing', 0.0, idx=1),
                   self._slice_spacing())
        if not all(value > 0 for value in spacing):
            return []
        # volume_conf 只在 ONNX 路径产出；手工编辑过蒙版后形状仍一致，故置信度沿用
        # 原推理结果——注意画笔改过的体素其置信度并非模型对新标签的置信度，
        # 这一点在定量面板的提示文案里已写明。
        return quantify.compute_organ_stats(self.volume_hu, self.volume_mask, spacing,
                                            self.organ_names, getattr(self, 'volume_conf', None))

    def _mesh3d_ready(self):
        """3D 表面重建只需几何有效、蒙版内有体素；不依赖 CT 专属的 HU 器官定量，
        否则 MR 病灶标注（hu_calibrated 按设计恒为假）会永远看不到 3D 预览。"""
        return bool(self.volume_mask is not None and self.volume_mask.any()
                    and all((getattr(self, 'canonical_orientation', False),
                             getattr(self, 'inplane_spacing_valid', False),
                             getattr(self, 'uniform_z_geometry_valid', False))))

    def _update_organ_stats(self):
        """刷新器官定量面板；无分割结果时清空并禁用导出按钮。3D 预览按钮的使能
        单独看 _mesh3d_ready，与器官 HU 定量是否可用无关。"""
        self._organ_stats = self._compute_organ_stats()
        self._refresh_paint_target()   # 无论有无器官都刷新画笔目标下拉
        self.btn_mesh3d.setEnabled(self._mesh3d_ready())
        if not self._organ_stats:
            self.lbl_ai_stats.setText("")
            self.btn_export_stats.setEnabled(False)
            return
        e = self.is_english
        lines = []
        for r in self._organ_stats:
            r_, g_, b_ = (int(LABEL_LUT[r['id']][0]), int(LABEL_LUT[r['id']][1]), int(LABEL_LUT[r['id']][2]))
            nm = r['name_en'] if e else r['name_zh']
            # 与椭圆 ROI 同口径给出 mean±SD：只报均值无法反映区域内密度离散程度
            txt = (f'<span style="color:#{r_:02X}{g_:02X}{b_:02X};">■</span> '
                   f"{nm}: {r['volume_ml']:.1f} mL / {r['mean_hu']:.0f}±{r['sd_hu']:.0f} HU")
            if 'mean_conf' in r:
                # 低置信标红：模型自己都不确信的器官，读数不该和高置信的一样呈现。
                # 阈值 0.9 取自 softmax 最大类概率的经验分界，仅作视觉提示，非诊断阈值。
                c = r['mean_conf']
                col = '#E67E22' if c < 0.9 else '#7F8C8D'
                extra = ''
                # 覆盖率明显不足 1 时必须标出：该器官已被大量手工改动，
                # 此时的 conf 只代表剩下那部分模型体素，不是整个器官的置信度
                if r.get('conf_cover', 1.0) < 0.98:
                    extra = (f" · {'model' if e else '模型判定'} {100*r['conf_cover']:.0f}%")
                txt += (f' <span style="color:{col};font-size:10px;">'
                        f"conf {c:.2f}/p5 {r['p5_conf']:.2f}{extra}</span>")
            lines.append(txt)
        # 置信度的口径说明做成悬停提示而非常驻文字：它是查一次就记住的静态解释，
        # 常驻会占掉两行并被面板宽度裁断（实测截图里就被裁成「多为边界体…」），
        # 而它旁边每一行都是随数据变化的实时读数，两者不该抢同样的版面。
        self.lbl_ai_stats.setToolTip(
            "conf = softmax max-probability; p5 = 5th percentile, mostly boundary voxels.\n"
            "Voxels edited by hand or written by 3D tracking are excluded — their stored\n"
            "value describes the label that was there before the edit."
            if e else
            "conf = 模型 softmax 最大类概率；p5 = 5% 分位，多为边界体素。\n"
            "画笔改过或 3D 追踪写入的体素不计入——它们的原值描述的是改动前那个标签。")
        self.lbl_ai_stats.setText("<br>".join(lines))
        self.btn_export_stats.setEnabled(True)

    def show_model_card(self):
        """弹出模型说明卡：出处如何被推断出来、实测到什么程度、有哪些已知局限。

        内容全部由 model_card 从已跑出的实验产物现读现算，不在 UI 层硬编码任何数字——
        实验重跑后卡片自动跟着变，避免界面上的指标与 results/ 里的产物各说各话。
        """
        dlg = QDialog(self)
        dlg.setWindowTitle(model_card.card_title(self.is_english))
        dlg.setStyleSheet(_DIALOG_STYLE)
        dlg.resize(560, 520)
        lay = QVBoxLayout(dlg)
        body = QLabel(model_card.build_model_card(self.is_english))
        body.setWordWrap(True); body.setTextFormat(Qt.RichText)
        body.setAlignment(Qt.AlignTop)
        body.setStyleSheet("font-size: 12px; line-height: 150%;")
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(body)
        lay.addWidget(sc)
        btn = QPushButton("Close" if self.is_english else "关闭")
        btn.clicked.connect(dlg.accept); lay.addWidget(btn)
        dlg.exec()

    def show_mesh3d(self):
        """对当前画笔目标所指器官做三维表面重建，弹窗展示四视角预览 + 形状特征 + STL 导出。

        取 cb_paint_target 的选中项作为对象，与画笔编辑保持同一"当前器官"语义，
        不再单设一个下拉——多一个状态就多一处可能不同步。
        """
        if not self._mesh3d_ready():
            return
        lid = self.cb_paint_target.currentData()
        e = self.is_english
        if lid is None or not (self.volume_mask == lid).any():
            QMessageBox.information(self, "3D", "Selected target has no voxels." if e
                                    else "所选目标在当前蒙版中没有体素。")
            return
        ds = self.dicom_datasets[0] if self.dicom_datasets else None
        # extract_surface 的 spacing 契约是 (行间距, 列间距, 层厚)，两者不可混用同一个值：
        # 面内各向异性时，网格的体积/表面积/球形度与导出 STL 的尺寸会整体错，而数量级
        # 仍然对得上，肉眼看不出来。此前这里传的是 (ps, ps, st)。
        ps_row = self._dcm_float(ds, 'PixelSpacing', 0.0, idx=0) if ds is not None else 0.0
        ps_col = self._dcm_float(ds, 'PixelSpacing', 0.0, idx=1) if ds is not None else 0.0
        # z 尺度取层间距而非层厚（重叠重建下二者可差一倍，网格会被拉伸/压扁）
        st = self._slice_spacing() if ds is not None else 0.0
        if not all(value > 0 for value in (ps_row, ps_col, st)):
            return
        # marching cubes 在 512² 体积上 step=1 约 1.4s、step=2 约 0.11s（实测），
        # 故取 2：这是交互预览，不是几何精算；耗时与精度的取舍在 mesh3d 模块注释里说明。
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            verts, faces = mesh3d.extract_surface(self.volume_mask, lid, (ps_row, ps_col, st), step=2)
            stats = mesh3d.mesh_shape_stats(verts, faces)
        finally:
            QApplication.restoreOverrideCursor()
        if len(faces) == 0:
            QMessageBox.information(self, "3D", "Too few voxels to build a surface." if e
                                    else "体素过少，无法构成表面。")
            return
        self._show_mesh_dialog(lid, verts, faces, stats)

    def _show_mesh_dialog(self, lid, verts, faces, stats):
        """三维预览弹窗：可鼠标拖动旋转的渲染视图 + 预设视角 + 形状特征 + STL 导出。"""
        e = self.is_english
        nm = next((r['name_en'] if e else r['name_zh'] for r in self._organ_stats if r['id'] == lid),
                  ("Manual annotation" if e else "手动标注") if lid == MANUAL_TRACK_LABEL else f"label {lid}")
        rgb = (int(LABEL_LUT[lid][0]), int(LABEL_LUT[lid][1]), int(LABEL_LUT[lid][2]))
        dlg = QDialog(self)
        dlg.setWindowTitle(f"3D · {nm}")
        dlg.setStyleSheet(_DIALOG_STYLE)
        lay = QVBoxLayout(dlg)

        # 拖动降质、松手提质：实测完整网格渲染约 100–140ms/帧，拖动时会明显顿挫；
        # 再减一档面到 grid=16（约 2000 面、~55ms）拖起来才跟手。松开鼠标后立刻用
        # 完整网格重渲染一帧，所以静止时看到的始终是全精度画面。
        # 这只影响预览显示——形状特征与 STL 导出一律用完整网格 verts/faces。
        dv, df = mesh3d.decimate_vertex_clustering(verts, faces, grid=16)
        SZ = 360
        view = MeshView(azimuth=30.0, elevation=20.0)
        view.setFixedSize(SZ, SZ)
        view.setStyleSheet("background:#0D1117; border:1px solid #30363D;")
        lb_ang = QLabel(); lb_ang.setStyleSheet(f"color:{_DIALOG_FG_MUTED}; font-size:10px;")

        def paint(v, f):
            arr = np.ascontiguousarray(mesh3d.render_mesh(v, f, size=SZ, azimuth=view.azimuth,
                                                          elevation=view.elevation, rgb=rgb))
            h, w = arr.shape[:2]
            view.setPixmap(QPixmap.fromImage(
                QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()))
            lb_ang.setText(("Azimuth %.0f° · Elevation %.0f° — drag to rotate" if e else
                            "方位角 %.0f° · 俯仰角 %.0f° —— 按住拖动可旋转")
                           % (view.azimuth, view.elevation))

        # 防重入：鼠标移动事件比一帧渲染密得多，不设闸门会积压成越拖越卡的事件队列。
        # 丢弃渲染中到达的中间帧不影响正确性——下一帧用的是控件里最新的绝对角度。
        busy = {'v': False}
        def on_rotate(_az, _el):
            if busy['v']: return
            busy['v'] = True
            try: paint(dv, df)
            finally: busy['v'] = False
        view.rotated.connect(on_rotate)
        view.settled.connect(lambda: paint(verts, faces))

        row = QHBoxLayout(); row.addWidget(view); row.addStretch()
        col = QVBoxLayout()
        col.addWidget(QLabel("View" if e else "视角"))
        for label_zh, label_en, az, el in (("前", "Ant", 90, 0), ("后", "Post", 270, 0),
                                           ("左", "Left", 180, 0), ("右", "Right", 0, 0),
                                           ("上", "Sup", 90, 89), ("斜", "Oblique", 30, 20)):
            b = QPushButton(label_en if e else label_zh); b.setFixedWidth(74)
            b.clicked.connect(lambda _=False, a=az, elv=el: view.set_angles(a, elv))
            col.addWidget(b)
        col.addStretch(); row.addLayout(col)
        lay.addLayout(row)
        lay.addWidget(lb_ang)
        paint(verts, faces)
        # 形状特征：体积可信；表面积/球形度受 marching cubes 阶梯效应系统性影响，
        # 故在界面上直接标注"相对比较用"，避免被当作绝对几何量引用。
        txt = (f"Surface {stats['surface_area_mm2'] / 100:.1f} cm² · "
               f"Volume {stats['volume_mm3'] / 1000:.1f} mL · "
               f"Sphericity {stats['sphericity']:.3f} · "
               f"{stats['n_faces']:,} faces" if e else
               f"表面积 {stats['surface_area_mm2'] / 100:.1f} cm² · "
               f"体积 {stats['volume_mm3'] / 1000:.1f} mL · "
               f"球形度 {stats['sphericity']:.3f} · "
               f"{stats['n_faces']:,} 面片")
        lb_s = QLabel(txt); lb_s.setStyleSheet(f"color:{_DIALOG_FG};"); lay.addWidget(lb_s)
        note = QLabel("Pipeline: marching cubes → Taubin smoothing → decimation. On an analytic "
                      "sphere: volume within 0.1%, surface area within ~1.3%."
                      if e else
                      "流程：marching cubes → Taubin 平滑 → 减面。解析球体验算：体积误差 0.1% 以内，"
                      "表面积误差约 1.3%。")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{_DIALOG_FG_MUTED}; font-size:10px;")
        lay.addWidget(note)
        btn = QPushButton("Export STL" if e else "导出 STL")
        btn.clicked.connect(lambda: self._export_stl(nm, verts, faces))
        lay.addWidget(btn)
        dlg.exec()

    def _export_stl(self, nm, verts, faces):
        """把网格写为 ASCII STL 到 Exported_Lesions/（文件名经 _safe_name 净化）。"""
        e = self.is_english
        ed = getattr(self, 'export_dir',
                     os.path.join(os.path.dirname(os.path.abspath(__file__)), "Exported_Lesions"))
        os.makedirs(ed, exist_ok=True)
        tag = self._export_tag() if self.anonymize else self._safe_name(
            str(getattr(self.dicom_datasets[0], 'PatientID', 'Unknown')))
        fp = self._unique_export_path(ed, f"{tag}_{self._safe_name(nm)}.stl")
        try:
            with open(fp, 'wb') as f:
                f.write(mesh3d.to_stl_bytes(verts, faces, self._safe_name(nm)))
            QMessageBox.information(self, "Success" if self.is_english else "成功",
                                    (f"Saved: {os.path.basename(fp)}" if self.is_english
                                     else f"已保存：{os.path.basename(fp)}"))
        except Exception as ex:
            QMessageBox.warning(self, "Export Failed" if e else "导出失败", str(ex))

    def _refresh_paint_target(self):
        """刷新画笔目标下拉：手动标注 + 当前蒙版中检出的各器官。
        让画笔可把修正直接补进指定器官（该器官定量随之更新），而非只写无名手动层。"""
        cur = self.cb_paint_target.currentData()
        e = self.is_english
        self.cb_paint_target.blockSignals(True)
        self.cb_paint_target.clear()
        self.cb_paint_target.addItem("Manual" if e else "手动标注", MANUAL_TRACK_LABEL)
        for r in self._organ_stats:
            if r['id'] == MANUAL_TRACK_LABEL:
                continue
            nm = r['name_en'] if e else r['name_zh']
            self.cb_paint_target.addItem(f"{nm} (#{r['id']})", r['id'])
        idx = self.cb_paint_target.findData(cur)
        self.cb_paint_target.setCurrentIndex(max(0, idx))
        self.cb_paint_target.blockSignals(False)

    def export_organ_stats(self):
        """将器官定量结果导出为 CSV（utf-8-sig 便于 Excel 正确显示中文）。"""
        rows = self._organ_stats or self._compute_organ_stats()
        if not rows:
            return
        tag = self._export_tag() if self.anonymize else self._safe_name(
            str(getattr(self.dicom_datasets[0], 'PatientID', 'Unknown')))
        ed = getattr(self, 'export_dir',
                     os.path.join(os.path.dirname(os.path.abspath(__file__)), "Exported_Lesions"))
        os.makedirs(ed, exist_ok=True)
        fp = self._unique_export_path(ed, f"{tag}_organ_stats.csv")
        try:
            with open(fp, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['# AI-derived, for reference only, NOT for diagnosis; organ labels are auto-inferred /'
                            ' AI 自动推断，仅供参考，非诊断依据'])
                # 置信度列只在模型真的产出概率时才写；数学降级路径没有概率，
                # 那时整列缺席，而不是填 0 或 1 让下游误以为有这个量
                has_conf = bool(rows) and 'mean_conf' in rows[0]
                hdr = ['class_id', 'organ_zh', 'organ_en', 'voxels', 'volume_mL',
                       'mean_HU', 'SD_HU', 'median_HU', 'p5_HU', 'p95_HU', 'min_HU', 'max_HU']
                w.writerow(hdr + (['mean_conf', 'p5_conf', 'conf_cover'] if has_conf else []))
                for r in rows:
                    row = [r['id'], r['name_zh'], r['name_en'], r['voxels'],
                           f"{r['volume_ml']:.2f}", f"{r['mean_hu']:.1f}", f"{r['sd_hu']:.1f}",
                           f"{r['median_hu']:.1f}", f"{r['p5_hu']:.1f}", f"{r['p95_hu']:.1f}",
                           f"{r['min_hu']:.1f}", f"{r['max_hu']:.1f}"]
                    if has_conf:
                        # conf_cover<1 表示该器官被手工改过，读数只覆盖剩余的模型体素
                        row += [f"{r.get('mean_conf', float('nan')):.4f}",
                                f"{r.get('p5_conf', float('nan')):.4f}",
                                f"{r.get('conf_cover', float('nan')):.4f}"]
                    w.writerow(row)
            QMessageBox.information(self, "Success" if self.is_english else "成功",
                                    (f"Saved: {os.path.basename(fp)}" if self.is_english
                                     else f"已保存：{os.path.basename(fp)}"))
        except Exception as ex:
            QMessageBox.warning(self, "Export Failed" if self.is_english else "导出失败", str(ex))

    def _update_legend(self, labels):
        """刷新图例：每个器官为可点击项（色块+名称），点击切换其在蒙版叠加中的显隐。
        已隐藏的项显示为灰色删除线。"""
        if len(labels) == 0:
            self.lbl_ai_legend.setText("")
            return
        e = self.is_english
        parts = []
        for lb in labels:
            lb = int(lb)
            r, g, b = (int(LABEL_LUT[lb][0]), int(LABEL_LUT[lb][1]), int(LABEL_LUT[lb][2]))
            name = self.organ_names.get(lb, (f"类{lb}", f"cls{lb}"))[1 if e else 0]
            hidden = lb in self._hidden_organs
            swatch = "#555555" if hidden else f"#{r:02X}{g:02X}{b:02X}"
            deco = "text-decoration:line-through; color:#666;" if hidden else "color:#B0B8C4;"
            parts.append(f'<a href="toggle:{lb}" style="text-decoration:none;">'
                         f'<span style="color:{swatch};">■</span>'
                         f'<span style="{deco}"> {name}</span></a>')
        title = "Detected: " if e else "检出器官: "
        self.lbl_ai_legend.setText(title + "&nbsp;&nbsp;".join(parts))

    def _toggle_organ(self, href):
        """图例项被点击：切换该器官类别在蒙版叠加中的显隐，并重绘。"""
        try:
            lid = int(href.split(":")[1])
        except (IndexError, ValueError):
            return
        self._hidden_organs.discard(lid) if lid in self._hidden_organs else self._hidden_organs.add(lid)
        if not self.recon_mode_active:
            self.update_display()  # 重绘 overlay，并经 _update_legend 刷新图例样式

    # =========================================================================
    # 标注渲染（仅 Axial，供 _render_clinical_plane 调用）
    # =========================================================================
    def _series_link_result(self, source_uid, target_uid):
        doc = self.study_document
        pair = series_registration.registration_pair(source_uid, target_uid)
        rid = doc.registration_links.get(pair)
        if rid is not None:
            result = series_registration.RegistrationResult.from_dict(doc.registrations[rid])
            series_registration.result_matrix(result, doc.series[source_uid].source, doc.series[target_uid].source)
            return result
        return series_registration.metadata_link(doc.series[source_uid].source, doc.series[target_uid].source)

    def _refresh_registration_controls(self):
        if not hasattr(self, 'cb_reference_series'):
            return
        e = self.is_english
        self.chk_series_location.setText('Keep patient location across series' if e else '切换序列时定位同一点')
        self.chk_reference_annotations.setText('Show reference annotations (read-only)' if e else '显示参考序列标注（只读）')
        self.cb_reference_series.setToolTip('Source series for corresponding annotations' if e else '对应标注的来源序列')
        previous = self.cb_reference_series.currentData()
        with QSignalBlocker(self.cb_reference_series):
            self.cb_reference_series.clear()
            if self.study_document:
                for sid, record in self.study_document.series.items():
                    if sid != self.active_series_uid and record.source is not None:
                        description = str(getattr(record.source.datasets[0], 'SeriesDescription', '') or sid[-12:])
                        self.cb_reference_series.addItem(f'{record.source.modality} · {description}', sid)
            index = self.cb_reference_series.findData(previous)
            if index >= 0:
                self.cb_reference_series.setCurrentIndex(index)
        self.cb_reference_series.setEnabled(self.cb_reference_series.count() > 0)
        self._refresh_series_link_status()
        self.btn_series_registration.setText('3-D rigid registration' if e else '三维刚性配准')
        self.btn_cancel_registration.setText('Cancel' if e else '取消配准')
        running = self._registration_worker is not None
        self.btn_series_registration.setEnabled(not running and self.cb_reference_series.count() > 0)
        self.btn_cancel_registration.setEnabled(running)

    def start_series_registration(self):
        if self._registration_worker is not None or self.study_document is None or self._leaving_document:
            return False
        sid = self.cb_reference_series.currentData(); doc = self.study_document
        try:
            moving, fixed = doc.series[sid].source, doc.series[self.active_series_uid].source
            if moving is None or fixed is None or moving.affine is None or fixed.affine is None:
                raise ValueError('Two connected series with valid patient-space geometry are required')
            self._stop_cine(); self._cancel_view_interactions()
            worker = SeriesRegistrationWorker(moving, fixed, doc.document_id, doc.revision,
                                                self._registration_generation, self)
            self._registration_worker = worker
            worker.finished.connect(self._on_series_registration_finished)
            self._refresh_registration_controls()
            self.lbl_series_link.setText('Computing 3-D candidate…' if self.is_english else '正在计算三维配准候选…')
            worker.start(); return True
        except (ValueError, KeyError, AttributeError) as exc:
            QMessageBox.information(self, 'Registration unavailable' if self.is_english else '无法配准', str(exc))
            return False

    def _cancel_series_registration(self):
        self._registration_generation += 1
        if self._registration_worker is not None:
            self._registration_worker.cancelled.set()

    def _review_registration(self, worker):
        dialog = RegistrationReviewDialog(worker.moving, worker.fixed, worker.result, self.is_english, self)
        return dialog.exec() == QDialog.Accepted

    def _on_series_registration_finished(self):
        worker = self.sender()
        if worker is not self._registration_worker:
            return
        self._registration_worker = None
        doc = self.study_document
        current = (doc is not None and worker.document_id == doc.document_id
                   and worker.generation == self._registration_generation and not self._leaving_document
                   and worker.revision == doc.revision)
        try:
            if not current or worker.cancelled.is_set():
                return
            if worker.error or worker.result is None:
                QMessageBox.information(self, 'Registration failed' if self.is_english else '配准未通过', worker.error or '')
                return
            doc.add_registration(worker.result, expected_revision=worker.revision)
            if self._review_registration(worker) and doc is self.study_document and worker.generation == self._registration_generation:
                reviewed = series_registration.mark_visually_reviewed(worker.result)
                doc.add_registration(reviewed); doc.adopt_registration(reviewed.result_id)
                self.chk_reference_annotations.setChecked(True)
            self._sync_committed_edit()
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            QMessageBox.information(self, 'Registration not adopted' if self.is_english else '未采用配准', str(exc))
        finally:
            worker.deleteLater(); self._refresh_registration_controls()

    def _refresh_series_link_status(self):
        sid = self.cb_reference_series.currentData(); e = self.is_english
        try:
            if sid is None or self.active_series_uid is None:
                raise ValueError('A second connected spatial series is required')
            result = self._series_link_result(sid, self.active_series_uid)
            status = {'metadata': ('Metadata location; motion unverified', '元数据定位；未验证扫描间运动'),
                      'reviewed': ('Rigid correspondence; visually reviewed', '刚性配准对应；已人工复核'),
                      'landmarks': ('Rigid correspondence; landmarks verified', '刚性配准对应；标志点验证通过')}
            self.lbl_series_link.setText(status[result.status][0 if e else 1]); self.lbl_series_link.setToolTip('')
            self.chk_reference_annotations.setEnabled(True)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            self.lbl_series_link.setText('No reliable correspondence' if e else '暂无可靠空间对应')
            self.lbl_series_link.setToolTip(str(exc)); self.chk_reference_annotations.setEnabled(False)
        self._refresh_linked_lesion_controls()

    def _on_reference_series_changed(self, *_):
        if not hasattr(self, 'lbl_series_link'):
            return
        self._refresh_series_link_status()
        if self.volume_hu is not None and not self.recon_mode_active and not self.compare_mode_active:
            self.update_display()

    def _render_reference_annotations(self, vdata):
        if not self.chk_reference_annotations.isChecked() or not self.chk_reference_annotations.isEnabled():
            return
        plane = vdata.get('patient_plane'); sid = self.cb_reference_series.currentData()
        if plane is None or sid is None or vdata['cb_proj'].currentIndex() != 0:
            return
        try:
            result = self._series_link_result(sid, self.active_series_uid)
            record = self.study_document.series[sid]; source = record.source
            mask = series_registration.sample_corresponding_plane(source, self._active_source, record.working_mask,
                                                                   plane, result, labels=True)
            rgba = np.zeros((*mask.shape, 4), np.uint8); rgba[mask != 0] = [255, 190, 60, 90]
            if np.any(mask):
                image = QImage(rgba.data, mask.shape[1], mask.shape[0], rgba.strides[0], QImage.Format_RGBA8888).copy()
                item = QGraphicsPixmapItem(QPixmap.fromImage(image)); item.setZValue(2.5)
                item.setData(11, 'series-reference'); item.setToolTip(f'Reference: {sid}')
                vdata['view'].scene.addItem(item)
            for annotations in record.annotations.values():
                for annotation in annotations:
                    projected = series_registration.project_corresponding_annotation(annotation, source, self._active_source, plane, result)
                    if not projected or not projected['points']:
                        continue
                    points = projected['points']; path = QPainterPath()
                    if projected['coplanar'] or (annotation['type'] == 'roi' and len(points) == 2):
                        path.moveTo(QPointF(*points[0]))
                        for point in points[1:]: path.lineTo(QPointF(*point))
                    else:
                        for x, y in points:
                            path.moveTo(x-.6,y); path.lineTo(x+.6,y); path.moveTo(x,y-.6); path.lineTo(x,y+.6)
                    item = QGraphicsPathItem(path); pen = QPen(QColor('#FFBE3C'), 2); pen.setStyle(Qt.DashLine)
                    item.setPen(pen); item.setZValue(3.5); item.setData(11, 'series-reference')
                    item.setToolTip(f'Reference: {sid} / {annotation["id"]}')
                    vdata['view'].scene.addItem(item)
        except (ValueError, KeyError, TypeError, AttributeError):
            return  # 显示热路径重复验证失败时不投影不可靠标注。

    def _render_annotations(self, vdata, z, sp):
        mapping = vdata.get('patient_plane')
        if vdata['plane'] == AXIAL and (mapping is None or self.canonical_orientation):
            self._render_source_annotations(vdata, z, sp)
        if mapping is None or self.study_document is None:
            return
        view = vdata['view']
        color = QColor('#00ADB5')
        for values in self.global_annotations.values():
            if not isinstance(values, list):
                continue
            for annotation in values:
                if not self._valid_anno(annotation) or not isinstance(annotation['id'], str):
                    continue
                space = annotation.get('space')
                if (not isinstance(space, dict) or space.get('kind') != 'patient'
                        or space.get('plane') not in (AXIAL, CORONAL, SAGITTAL)):
                    continue
                # 与旧来源切片渲染保持同一容错边界：坏对象不能阻断后续有效对象。
                try:
                    projected = mpr_geometry.project_annotation(annotation, mapping)
                except (ValueError, TypeError, KeyError, IndexError):
                    continue
                points = projected['points']
                if not points:
                    continue
                kind = annotation['type']
                native = projected['coplanar'] and annotation['space']['plane'] == vdata['plane']
                text = None
                if native and kind == 'roi' and self._display_layer_id is None:
                    # 创建平面的真实轮廓重投影，ROI 移动只经事务回调提交。
                    coords = np.asarray(points)
                    low, high = coords.min(axis=0), coords.max(axis=0)
                    if np.any(high <= low):
                        continue
                    shown = deepcopy(annotation)
                    shown['rect'] = (*low.tolist(), *(high - low).tolist())
                    item = ROIGraphicsItem(shown, None,
                               on_geometry_change=self._roi_change_callback(vdata, annotation))
                    item.set_appearance(color)
                    image = vdata.get('annotation_intensity')
                    if image is not None:
                        yy, xx = np.indices(image.shape)
                        center, radii = (low + high) / 2, (high - low) / 2
                        inside = (((xx + .5 - center[0]) / radii[0]) ** 2
                                  + ((yy + .5 - center[1]) / radii[1]) ** 2 <= 1)
                        samples = image[inside]
                        if samples.size:
                            unit = 'HU' if self.hu_calibrated else ('stored' if self.is_english else '原始值')
                            area = np.pi * radii[0] * radii[1] * sp[0] * sp[1]
                            text = f'{samples.mean():.1f}±{samples.std():.1f} {unit}\n{area:.1f} mm²'
                elif projected['coplanar'] or (kind == 'roi' and len(points) == 2):
                    path = QPainterPath(QPointF(*points[0]))
                    for point in points[1:]:
                        path.lineTo(QPointF(*point))
                    item = QGraphicsPathItem(path)
                    item.setPen(QPen(color, 2))
                    if kind == 'ruler' and projected['coplanar']:
                        lps = np.asarray(annotation['space']['points_lps'])
                        text = f'{np.linalg.norm(lps[-1] - lps[0]):.1f} mm'
                else:
                    # 非创建平面只标出实际交点，不画一份无空间含义的完整二维对象。
                    path = QPainterPath()
                    for x, y in points:
                        path.moveTo(x - .6, y); path.lineTo(x + .6, y)
                        path.moveTo(x, y - .6); path.lineTo(x, y + .6)
                    item = QGraphicsPathItem(path)
                    item.setPen(QPen(color, 2))
                item.setToolTip(annotation['id']); item.setZValue(3)
                item.setFlag(QGraphicsItem.ItemIsSelectable, True)
                view.scene.addItem(item)
                if text:
                    label = QGraphicsTextItem(text); label.setDefaultTextColor(color)
                    label.setFont(QFont('Arial', 10, QFont.Bold)); label.setZValue(4)
                    width, height = _pin_text_to_screen(label, view)
                    h, w = mapping.shape
                    label.setPos(max(0., min(points[-1][0] + 2, w - width)),
                                 max(0., min(points[-1][1] + 2, h - height)))
                    view.scene.addItem(label)

        self._render_reference_annotations(vdata)

    def _render_source_annotations(self, vdata, z, sp):
        """在视图场景中渲染当前切片的标注图元（仅 Axial 平面调用）。
        颜色区分：切片专属标注用青色，全局穿透标注用黄色；分组遍历避免 O(n²) 成员检查。
        """
        col_slice = QColor("#00ADB5")
        col_global = QColor("#F1C40F")
        slice_annos = self.global_annotations.get(z, [])
        global_annos = self.global_annotations.get('all', [])
        for annos, col in ((slice_annos, col_slice), (global_annos, col_global)):
            if not isinstance(annos, list):
                continue
            for anno in annos:
              # 逐条兜底：万一有畸形标注漏过加载期过滤，也只跳过这一条，绝不拖垮整次刷新
              try:
                if anno['type'] == 'ruler':
                    line = QGraphicsLineItem(QLineF(anno['p1'][0], anno['p1'][1], anno['p2'][0], anno['p2'][1]))
                    line.setPen(QPen(col, 2))
                    line.setToolTip(anno['id'])          # toolTip 存 UUID，Delete 键删除时用
                    line.setFlag(QGraphicsLineItem.ItemIsSelectable)
                    vdata['view'].scene.addItem(line)
                    if getattr(self, 'inplane_spacing_valid', False):
                        dist = math.sqrt(
                            ((anno['p2'][0] - anno['p1'][0]) * sp[1]) ** 2 +
                            ((anno['p2'][1] - anno['p1'][1]) * sp[0]) ** 2
                        )
                        label = f"{dist:.1f} mm"
                    else:
                        label = "distance unavailable" if self.is_english else "距离不可用"
                    txt = QGraphicsTextItem(label)
                    txt.setDefaultTextColor(col)
                    txt.setFont(QFont("Arial", 11, QFont.Bold))
                    tw, th = _pin_text_to_screen(txt, vdata['view'])
                    H, W = self.volume_hu.shape[1], self.volume_hu.shape[2]
                    tx = anno['p2'][0] + 10
                    if tx + tw > W:                 # 右侧放不下就翻到测量终点左边
                        tx = max(0.0, anno['p2'][0] - 10 - tw)
                    ty = min(max(0.0, anno['p2'][1] + 10), max(0.0, H - th))
                    txt.setPos(tx, ty)
                    vdata['view'].scene.addItem(txt)
                elif anno['type'] == 'path':
                    pts = anno['points']
                    path = QPainterPath(QPointF(pts[0][0], pts[0][1]))
                    for p in pts[1:]:
                        path.lineTo(QPointF(p[0], p[1]))
                    pen = QPen(col, 2)
                    pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
                    item = QGraphicsPathItem(path)
                    item.setPen(pen)
                    item.setFlag(QGraphicsPathItem.ItemIsSelectable)
                    item.setToolTip(anno['id'])
                    vdata['view'].scene.addItem(item)
                elif anno['type'] == 'roi':
                    rx0, ry0, rw, rh = anno['rect']
                    # 可拖动+可缩放的 ROI；改动后经 update_display 回调重算统计并重绘
                    ell = ROIGraphicsItem(anno, self.update_display,
                              on_geometry_change=self._roi_change_callback(vdata, anno))
                    ell.setEnabled(self._display_layer_id is None)
                    ell.set_appearance(col)
                    ell.setToolTip(anno['id'])
                    vdata['view'].scene.addItem(ell)
                    # 椭圆内 HU 统计：用 numpy 椭圆掩码取 volume_hu[z] 内部体素
                    H, W = self.volume_hu.shape[1], self.volume_hu.shape[2]
                    cx, cy = rx0 + rw / 2.0, ry0 + rh / 2.0
                    ax, ay = max(rw / 2.0, 0.5), max(rh / 2.0, 0.5)
                    yy, xx = np.ogrid[:H, :W]
                    emask = ((xx - cx) / ax) ** 2 + ((yy - cy) / ay) ** 2 <= 1.0
                    vals = self.volume_hu[z][emask]
                    if vals.size:
                        parts = []
                        if getattr(self, 'hu_calibrated', False):
                            parts += [f"{vals.mean():.0f}±{vals.std():.0f} HU",
                                      f"[{vals.min():.0f}, {vals.max():.0f}]"]
                        else:
                            parts.append("HU unavailable" if self.is_english else "HU 不可用")
                        if getattr(self, 'inplane_spacing_valid', False):
                            area = vals.size * sp[0] * sp[1]
                            parts.append(f"{area:.0f} mm²")
                        else:
                            parts.append("area unavailable" if self.is_english else "面积不可用")
                        stat = "\n".join(parts)
                        txt = QGraphicsTextItem(stat)
                        txt.setDefaultTextColor(col)
                        txt.setFont(QFont("Arial", 10, QFont.Bold))
                        # 防跑出画面：右侧放不下则移到椭圆左侧，纵向夹取在图像内。
                        # 尺寸按实际字体度量折算，不用写死的常量——此前的 95/46 是在
                        # 某一个缩放下估的，换个缩放就既挡图又溢出边界。
                        tw, th = _pin_text_to_screen(txt, vdata['view'])
                        tx = rx0 + rw + 4
                        if tx + tw > W:
                            tx = max(0.0, rx0 - tw - 4)
                        ty = min(max(0.0, ry0), max(0.0, H - th))
                        txt.setPos(tx, ty)
                        vdata['view'].scene.addItem(txt)
              except Exception as _e:
                  print(f"跳过畸形标注: {_e}")
                  continue
