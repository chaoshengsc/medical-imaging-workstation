"""CT/MR 来源网格、患者空间与检查文档；无 Qt，无模型推理副作用。"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

import numpy as np
import pydicom
from pydicom.uid import CTImageStorage, MRImageStorage

from annotation_state import (
    AnnotationLayer,
    EditHistory,
    add_ai_result,
    adopt_ai_command,
    adopt_registration_command,
    annotations_command,
    create_lesion_command,
    mask_command,
    replace_mask_command,
)
from dicom_geometry import SeriesGeometry, analyze_series, series_fingerprint
from series_registration import result_matrix, validate_registration_state


def _int_tag(ds, name, default=0):
    """DICOM 整数侧 helper；空值和非有限数字不能泄漏到排序/shape。"""
    try:
        value = getattr(ds, name, default)
        return default if value is None else int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def is_supported_classic_image(ds):
    modality = str(getattr(ds, 'Modality', '')).upper()
    return (str(getattr(ds, 'SOPClassUID', '')) ==
            {'CT': str(CTImageStorage), 'MR': str(MRImageStorage)}.get(modality, '!')
            and (not hasattr(ds, 'NumberOfFrames') or _int_tag(ds, 'NumberOfFrames', -1) == 1)
            and not hasattr(ds, 'SharedFunctionalGroupsSequence')
            and not hasattr(ds, 'PerFrameFunctionalGroupsSequence'))


def _uid(ds, name):
    return str(getattr(ds, name, '') or '').strip()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _source_binding(datasets, frames, unit):
    study, series = _uid(datasets[0], 'StudyInstanceUID'), _uid(datasets[0], 'SeriesInstanceUID')
    sops = [_uid(ds, 'SOPInstanceUID') for ds in datasets]
    if (not study or not series or not all(sops) or len(set(sops)) != len(sops)
            or any(_uid(ds, 'StudyInstanceUID') != study
                   or _uid(ds, 'SeriesInstanceUID') != series for ds in datasets)):
        return None
    frame_ids = []
    for ds, raw in zip(datasets, frames, strict=True):
        if (_int_tag(ds, 'Rows'), _int_tag(ds, 'Columns')) != raw.shape:
            return None
        # 对解码后的原始样本做摘要，传输语法/文件移动不改变标注来源。
        pixels = np.ascontiguousarray(raw, dtype=raw.dtype.newbyteorder('<'))
        frame_ids.append({'sop': _uid(ds, 'SOPInstanceUID'), 'dtype': pixels.dtype.str,
                          'pixels': hashlib.sha256(pixels.tobytes()).hexdigest(),
                          'rescale': [float(ds.RescaleSlope), float(ds.RescaleIntercept)]
                          if unit == 'HU' else None})
    payload = {'schema': 'dicom-source-v1', 'study_uid': study, 'series_uid': series,
               'shape': [len(frames), *frames[0].shape], 'array_order': 'zyx',
               'modality': str(datasets[0].Modality), 'unit': unit, 'frames': frame_ids}
    return {**payload, 'digest': _digest(payload)}


def _source_affine(datasets, geometry):
    if not (geometry.inplane_spacing_valid and geometry.uniform_z_geometry_valid):
        return None
    ds = datasets[0]
    iop = np.asarray(ds.ImageOrientationPatient, dtype=float)
    spacing = np.asarray(ds.PixelSpacing, dtype=float)
    affine = np.eye(4)
    # affine 输入 (x,y,z)，数组仍为 [z,y,x]；绝不以 SliceThickness 填缺失层距。
    affine[:3, 0] = iop[:3] * spacing[1]
    affine[:3, 1] = iop[3:] * spacing[0]
    affine[:3, 2] = np.cross(iop[:3], iop[3:]) * geometry.slice_spacing_mm
    affine[:3, 3] = np.asarray(ds.ImagePositionPatient, dtype=float)
    affine.flags.writeable = False
    return affine


@dataclass(frozen=True)
class SeriesVolume:
    """完整解码但尚未接入 UI 的序列；缺来源绑定时只允许阅片。"""

    datasets: tuple
    volume: np.ndarray
    geometry: SeriesGeometry
    source_binding: dict | None
    affine: np.ndarray | None
    intensity_unit: str

    @property
    def study_uid(self):
        return _uid(self.datasets[0], 'StudyInstanceUID')

    @property
    def series_uid(self):
        return _uid(self.datasets[0], 'SeriesInstanceUID')

    @property
    def modality(self):
        return str(self.datasets[0].Modality).upper()

    @property
    def geometry_binding(self):
        if self.affine is None:
            return None
        return {'schema': 'dicom-space-v1', 'affine_lps': self.affine.tolist(),
                'fingerprint': series_fingerprint(self.datasets, self.volume.shape)}

    @classmethod
    def from_datasets(cls, datasets):
        datasets = tuple(datasets)
        if not datasets or not all(is_supported_classic_image(ds) for ds in datasets):
            raise ValueError('Only Classic single-frame CT/MR images are supported')
        if len({str(ds.Modality).upper() for ds in datasets}) != 1:
            raise ValueError('A series cannot mix CT and MR')
        geometry = analyze_series(datasets)
        order = (geometry.sort_indices if geometry.sort_indices is not None else
                 sorted(range(len(datasets)),
                        key=lambda i: (_int_tag(datasets[i], 'InstanceNumber'),
                                       _uid(datasets[i], 'SOPInstanceUID'))))
        datasets = tuple(datasets[i] for i in order)
        frames = [np.asarray(ds.pixel_array) for ds in datasets]
        if any(raw.ndim != 2 or raw.shape != frames[0].shape for raw in frames):
            raise ValueError('A source grid requires consistent single-frame matrices')
        geometry = analyze_series(datasets)
        # HU 证明仅在 CT 入口有效：MRI 中的 rescale 标签不能开放 CT consumers。
        if str(datasets[0].Modality).upper() != 'CT':
            geometry = replace(geometry, hu_calibrated=False)
        unit = 'HU' if geometry.hu_calibrated else 'stored'
        binding = _source_binding(datasets, frames, unit)
        volume = np.stack([raw.astype(np.float32) * float(ds.RescaleSlope)
                           + float(ds.RescaleIntercept) if unit == 'HU'
                           else raw.astype(np.float32)
                           for ds, raw in zip(datasets, frames, strict=True)])
        if not np.all(np.isfinite(volume)):
            raise ValueError('Decoded intensities must be finite')
        volume.flags.writeable = False
        return cls(datasets, volume, geometry, binding,
                   _source_affine(datasets, geometry), unit)


@dataclass(frozen=True)
class ReadResult:
    series: tuple[SeriesVolume, ...]
    warnings: tuple[str, ...]


@dataclass(init=False)
class SeriesRecord:
    """序列状态独立于当前显示；切换序列只更换 UI 引用。"""

    source: SeriesVolume | None
    source_binding: dict | None
    geometry_binding: dict | None
    layers: dict[str, AnnotationLayer]
    active_layer_id: str
    annotations: dict = field(default_factory=lambda: {'all': []})
    cursor: list = field(default_factory=lambda: [0, 0, 0])
    ai_status: dict = field(default_factory=dict)
    visited: bool = False
    statistics: list = field(default_factory=list)

    def __init__(self, source, source_binding, geometry_binding, working_mask, confidence=None,
                 annotations=None, cursor=None):
        self.source, self.source_binding, self.geometry_binding = source, source_binding, geometry_binding
        self.active_layer_id = 'working-organs'
        self.layers = {self.active_layer_id: AnnotationLayer(self.active_layer_id, working_mask, confidence)}
        self.layers['working-manual'] = AnnotationLayer('working-manual', np.zeros_like(working_mask),
            kind='lesion', provenance={'origin': 'manual', 'modified': False}, lesion_id=uuid.uuid4().hex)
        self.annotations = {'all': []} if annotations is None else annotations
        self.cursor = [0, 0, 0] if cursor is None else cursor
        self.ai_status, self.visited = {}, False
        self.statistics = []

    @property
    def working_mask(self):
        return self.layers[self.active_layer_id].mask

    @working_mask.setter
    def working_mask(self, value):
        self.layers[self.active_layer_id].mask = value

    @property
    def confidence(self):
        return self.layers[self.active_layer_id].confidence

    @confidence.setter
    def confidence(self, value):
        self.layers[self.active_layer_id].confidence = value

    @classmethod
    def from_source(cls, source):
        return cls(source, source.source_binding, source.geometry_binding,
                   np.zeros(source.volume.shape, dtype=np.uint8),
                   cursor=[int(s // 2) for s in source.volume.shape])


@dataclass
class StudyDocument:
    study_uid: str
    series: dict[str, SeriesRecord] = field(default_factory=dict)
    document_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    revision: int = 0
    saved_revision: int = 0
    history: EditHistory = field(default_factory=EditHistory)
    project_path: str | None = None
    saved_at: str = ''
    registrations: dict = field(default_factory=dict)
    registration_links: dict = field(default_factory=dict)
    recovery: dict | None = None
    on_change: Callable | None = field(default=None, repr=False, compare=False)

    def notify_changed(self):
        if self.on_change is not None:
            self.on_change(self)

    def edit_mask(self, series_uid, indices, value, *, view_plane=None, **kwargs):
        command = mask_command(self, series_uid, indices, value, **kwargs)
        return self.history.commit(self, replace(command, view_plane=view_plane) if command else None)

    def edit_annotations(self, series_uid, annotations, *, view_plane=None, **kwargs):
        command = annotations_command(self, series_uid, annotations, **kwargs)
        return self.history.commit(self, replace(command, view_plane=view_plane) if command else None)

    def undo(self):
        return self.history.undo(self)

    def add_ai_result(self, series_uid, mask, confidence, provenance, **kwargs):
        return add_ai_result(self, series_uid, mask, confidence, provenance, **kwargs)

    def adopt_ai_result(self, series_uid, version, **kwargs):
        return self.history.commit(self, adopt_ai_command(self, series_uid, version, **kwargs))

    def replace_mask(self, series_uid, mask, confidence, *, view_plane=None, **kwargs):
        command = replace_mask_command(self, series_uid, mask, confidence, **kwargs)
        return self.history.commit(self, replace(command, view_plane=view_plane) if command else None)

    def create_lesion_layer(self, series_uid, **kwargs):
        command = self.history.commit(self, create_lesion_command(self, series_uid, **kwargs))
        return command.created_layer['layer_id']

    def add_registration(self, result, *, expected_revision=None):
        if expected_revision is not None and expected_revision != self.revision:
            raise ValueError('Registration callback belongs to a stale input revision')
        if result.result_id in self.registrations:
            raise ValueError('Registration result versions are immutable')
        payload = result.to_dict()
        validate_registration_state({result.result_id: payload}, {}, self.series, require_connected=True)
        result_matrix(result, self.series[result.moving_sid].source, self.series[result.fixed_sid].source,
                      allow_candidate=True)
        self.registrations[result.result_id] = payload
        self.revision += 1; self.notify_changed()

    def adopt_registration(self, result_id):
        return self.history.commit(self, adopt_registration_command(self, result_id))

    def attach_sources(self, sources):
        """先检查全部候选再接入；已有来源错配不能造成部分替换。"""
        proposed = []
        seen = set()
        for source in sources:
            if source.study_uid != self.study_uid:
                raise ValueError('Cannot attach another Study to this document')
            uid = source.series_uid or f'unbound-{uuid.uuid4().hex}'
            if uid in seen:
                raise ValueError('Duplicate SeriesInstanceUID in candidate document')
            seen.add(uid)
            existing = self.series.get(uid)
            if existing is not None and (not existing.source_binding
                    or existing.source_binding != source.source_binding
                    or existing.geometry_binding != source.geometry_binding):
                raise ValueError('Source identity or geometry changed; existing annotations retained')
            proposed.append((uid, source, existing))
        for uid, source, existing in proposed:
            if existing is None:
                self.series[uid] = SeriesRecord.from_source(source)
                self.revision += 1
            else:
                existing.source = source
        if any(existing is None for _, _, existing in proposed):
            self.notify_changed()


def read_series_directory(path) -> ReadResult:
    """读盘、解码和校验全部发生在独立候选中，调用方决定何时接入主文档。"""
    paths = []
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        paths.extend(os.path.join(root, name) for name in sorted(files) if not name.startswith('.'))

    def read_one(filename):
        try:
            return pydicom.dcmread(filename)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(16, (os.cpu_count() or 4) * 2)) as pool:
        datasets = [ds for ds in pool.map(read_one, paths) if ds is not None and 'PixelData' in ds]
    warnings = []
    supported = [ds for ds in datasets if is_supported_classic_image(ds)]
    unsupported = len(datasets) - len(supported)
    if unsupported:
        warnings.append(f'{unsupported} unsupported images (requires Classic single-frame CT/MR)')
    if len(supported) > 1 and any(not _uid(ds, 'SeriesInstanceUID') for ds in supported):
        return ReadResult((), (*warnings, 'Multiple source frames require SeriesInstanceUID'))
    groups = defaultdict(list)
    for ds in supported:
        groups[(_uid(ds, 'StudyInstanceUID'), _uid(ds, 'SeriesInstanceUID'))].append(ds)
    candidates = []
    for group in groups.values():
        # 保留旧 reader 的可解码主矩阵预览语义；被舍弃帧有明确告警，来源摘要只绑定实际帧。
        shapes = defaultdict(list)
        for ds in group:
            try:
                raw = ds.pixel_array
                if raw.ndim != 2:
                    raise ValueError('not a single 2D frame')
                shapes[raw.shape].append(ds)
            except Exception as exc:
                warnings.append(f'Undecodable frame: {type(exc).__name__}')
        if not shapes:
            continue
        selected = max(shapes.values(), key=len)
        if len(shapes) > 1:
            warnings.append(f'Mixed matrices: retained {len(selected)} of {sum(map(len, shapes.values()))} frames')
        try:
            candidates.append(SeriesVolume.from_datasets(selected))
        except (ValueError, TypeError, OverflowError) as exc:
            warnings.append(f'Invalid series: {exc}')
    if not candidates:
        warnings.append('No decodable Classic CT/MR series found')
    return ReadResult(tuple(candidates), tuple(warnings))
