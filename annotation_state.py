"""已提交标注事务与有界历史；不持有 Qt 对象，不在鼠标预览时修改文档。"""

from __future__ import annotations

import json
import uuid
import zlib
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from series_registration import RegistrationResult, registration_pair, validate_registration_state

_CHUNK_VOXELS = 262144
_PATCH_DTYPE = np.dtype([('index', '<u4'), ('before', 'u1'), ('after', 'u1'),
                         ('conf_before', 'u1'), ('conf_after', 'u1')])


def _bound_record(document, series_uid):
    record = document.series.get(series_uid)
    if record is None or record.source is None:
        raise ValueError('Source series is not connected; reconnect it before editing or Undo')
    if (not record.source_binding or record.source_binding != record.source.source_binding
            or record.geometry_binding != record.source.geometry_binding):
        raise ValueError('Source identity or geometry is not verified')
    return record


@dataclass
class AnnotationLayer:
    layer_id: str
    mask: np.ndarray
    confidence: np.ndarray | None = None
    kind: str = 'organ'
    readonly: bool = False
    provenance: dict = field(default_factory=lambda: {'origin': 'empty', 'modified': False})
    lesion_id: str | None = None


@dataclass(frozen=True)
class MaskChunk:
    """单块中的局部差分；大范围操作也不保留 20 份整卷数组。"""

    start: int
    count: int
    data: bytes

    def decode(self):
        if (type(self.count) is not int or not 0 < self.count <= _CHUNK_VOXELS
                or type(self.start) is not int or self.start < 0 or self.start % _CHUNK_VOXELS):
            raise ValueError('Invalid history block bounds')
        expected = self.count * _PATCH_DTYPE.itemsize
        decoder = zlib.decompressobj()
        raw = decoder.decompress(self.data, expected + 1)
        if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('Invalid history block size')
        decoded = np.frombuffer(raw, dtype=_PATCH_DTYPE)
        if np.any(decoded['index'] >= _CHUNK_VOXELS):
            raise ValueError('Invalid history block index')
        return decoded


@dataclass(frozen=True)
class EditCommand:
    series_uid: str
    source_digest: str
    geometry_binding: dict | None
    cursor: tuple
    description: str
    layer_id: str | None = None
    chunks: tuple[MaskChunk, ...] = ()
    confidence_before_present: bool = False
    confidence_after_present: bool = False
    provenance_before: dict | None = None
    provenance_after: dict | None = None
    annotations_before: dict | None = None
    annotations_after: dict | None = None
    created_layer: dict | None = None
    view_plane: int | None = None
    operation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    registration_pair: str | None = None
    registration_before: str | None = None
    registration_after: str | None = None

    def apply(self, document, *, undo=False):
        record = _bound_record(document, self.series_uid)
        if (record.source_binding['digest'] != self.source_digest
                or record.geometry_binding != self.geometry_binding):
            raise ValueError('History belongs to a different source grid')
        next_link = None
        if self.registration_pair is not None:
            if self.layer_id is not None or self.annotations_before is not None or self.created_layer is not None:
                raise ValueError('Registration adoption cannot contain unrelated editing payloads')
            expected_link = self.registration_after if undo else self.registration_before
            next_link = self.registration_before if undo else self.registration_after
            if document.registration_links.get(self.registration_pair) != expected_link:
                raise ValueError('Registration link no longer matches the history boundary')
            results = {rid: document.registrations[rid] for rid in (self.registration_before, self.registration_after) if rid}
            for rid in results:
                validate_registration_state({rid: results[rid]}, {self.registration_pair: rid},
                                            document.series, require_connected=True)
        created = None
        if self.created_layer is not None:
            meta = self.created_layer
            present = record.layers.get(meta['layer_id'])
            if undo:
                if (present is None or present.readonly or present.mask.any()
                        or present.confidence is not None or present.lesion_id != meta['lesion_id']):
                    raise ValueError('Created layer no longer matches its empty history boundary')
            else:
                if present is not None:
                    raise ValueError('Layer identity already exists')
                created = AnnotationLayer(meta['layer_id'], np.zeros(record.working_mask.shape, np.uint8),
                    kind='lesion', lesion_id=meta['lesion_id'], provenance=deepcopy(meta['provenance']))
        old, new = ('after', 'before') if undo else ('before', 'after')
        expected = self.annotations_after if undo else self.annotations_before
        replacement = self.annotations_before if undo else self.annotations_after
        if expected is not None and record.annotations != expected:
            raise ValueError('Annotations no longer match the history boundary')
        layer = record.layers.get(self.layer_id) if self.layer_id is not None else None
        if self.layer_id is not None and (layer is None or layer.readonly):
            raise ValueError('History target must be an editable layer')
        expected_provenance = self.provenance_after if undo else self.provenance_before
        target_provenance = self.provenance_before if undo else self.provenance_after
        if layer is not None and layer.provenance != expected_provenance:
            raise ValueError('Layer provenance no longer matches the history boundary')
        mask = layer.mask.ravel() if layer is not None else None
        confidence = layer.confidence if layer is not None else None
        cf_old = self.confidence_after_present if undo else self.confidence_before_present
        cf_new = self.confidence_before_present if undo else self.confidence_after_present
        if layer is not None and (confidence is not None) != cf_old:
            raise ValueError('Confidence no longer matches the history boundary')
        confidence = None if confidence is None else confidence.ravel()
        decoded = []
        previous_end = -1
        # 先完整验证差分与当前状态，再统一提交；损坏历史不能造成半次 Undo。
        for chunk in self.chunks:
            delta = chunk.decode()
            indices = delta['index'].astype(np.int64) + chunk.start
            if (mask is None or not len(indices) or indices[0] <= previous_end
                    or np.any(indices < 0) or np.any(indices >= mask.size)
                    or np.any(np.diff(indices) <= 0)
                    or not np.array_equal(mask[indices], delta[old])
                    or (confidence is not None
                        and not np.array_equal(confidence[indices], delta[f'conf_{old}']))):
                raise ValueError('Mask no longer matches the history boundary')
            decoded.append((indices, delta))
            previous_end = indices[-1]
        annotations = deepcopy(replacement) if replacement is not None else None
        provenance = deepcopy(target_provenance)
        if layer is not None and cf_new and confidence is None:
            confidence = np.zeros(layer.mask.size, dtype=np.uint8)
        elif not cf_new:
            confidence = None
        # 保存持有只读 revision 时仅复制本次被写的层；其他序列与 AI 原始层继续共享。
        if decoded and not mask.flags.writeable:
            mask = mask.copy()
        if decoded and confidence is not None and not confidence.flags.writeable:
            confidence = confidence.copy()
        for indices, delta in decoded:
            mask[indices] = delta[new]
            if confidence is not None:
                confidence[indices] = delta[f'conf_{new}']
        if annotations is not None:
            record.annotations = annotations
        if layer is not None:
            layer.mask = mask.reshape(layer.mask.shape)
            layer.confidence = confidence.reshape(layer.mask.shape) if cf_new else None
            layer.provenance = provenance
        if self.created_layer is not None:
            if undo:
                del record.layers[self.created_layer['layer_id']]
                if record.active_layer_id == self.created_layer['layer_id']:
                    record.active_layer_id = self.created_layer['previous_active']
            else:
                record.layers[created.layer_id] = created
        if self.registration_pair is not None:
            if next_link is None:
                document.registration_links.pop(self.registration_pair, None)
            else:
                document.registration_links[self.registration_pair] = next_link
        document.revision += 1


@dataclass
class EditHistory:
    commands: list[EditCommand] = field(default_factory=list)
    limit: int = 20

    def __len__(self):
        return len(self.commands)

    def commit(self, document, command):
        if command is None:
            return None
        command.apply(document)
        self.commands.append(command)
        del self.commands[:-self.limit]
        document.notify_changed()
        return command

    def undo(self, document):
        if not self.commands:
            return None
        command = self.commands[-1]
        command.apply(document, undo=True)
        self.commands.pop()  # 未连接来源/校验失败时保留栈顶，不跳过它回退更早编辑。
        document.notify_changed()
        return command


def adopt_registration_command(document, result_id):
    result = RegistrationResult.from_dict(document.registrations[result_id])
    pair = registration_pair(result.moving_sid, result.fixed_sid)
    old = document.registration_links.get(pair)
    if old == result_id:
        return None
    record = _bound_record(document, result.moving_sid)
    return EditCommand(result.moving_sid, record.source_binding['digest'], deepcopy(record.geometry_binding),
        tuple(record.cursor), 'Adopt 3-D registration', registration_pair=pair,
        registration_before=old, registration_after=result_id)


def mask_command(document, series_uid, indices, value, *, cursor=None, description='Paint', layer_id=None):
    record = _bound_record(document, series_uid)
    layer = record.layers[layer_id or record.active_layer_id]
    provenance = {**layer.provenance, 'modified': True}
    return _mask_change(record, series_uid, layer, indices, value, 0,
                        layer.confidence is not None, provenance, cursor, description)


def _mask_change(record, series_uid, layer, indices, value, target_confidence,
                 has_target_confidence, provenance, cursor, description):
    mask = layer.mask
    if layer.readonly:
        raise ValueError('Original AI result is read-only')
    if mask.dtype != np.uint8 or mask.ndim != 3 or not mask.flags.c_contiguous:
        raise ValueError('Editable labels require a contiguous 3-D uint8 source grid')
    value = np.asarray(value)
    if (value.dtype.kind not in 'iu' or np.any(value < 0) or np.any(value > 255)
            or (value.ndim != 0 and value.shape != mask.shape)):
        raise ValueError('Labels must be integers in [0, 255] on the source grid')
    target = value.ravel() if value.ndim else int(value)
    target_confidence = np.asarray(target_confidence)
    if (target_confidence.dtype.kind not in 'iu' or np.any(target_confidence < 0)
            or np.any(target_confidence > 255)
            or (target_confidence.ndim != 0 and target_confidence.shape != mask.shape)):
        raise ValueError('Confidence must be uint8 values on the source grid')
    target_cf = target_confidence.ravel() if target_confidence.ndim else int(target_confidence)
    indices = np.asarray(indices) if indices is not None else None
    if indices is None:
        selection = None
        blocks = range(0, mask.size, _CHUNK_VOXELS)
    elif indices.dtype == bool:
        if indices.shape != mask.shape:
            raise ValueError('Selection must match the source grid')
        selection = indices.ravel()
        blocks = range(0, mask.size, _CHUNK_VOXELS)
    else:
        if indices.size and (indices.dtype.kind not in 'iu'
                             or np.any(indices < 0) or np.any(indices >= mask.size)):
            raise ValueError('Voxel index outside the source grid')
        indices = np.unique(indices.astype(np.int64).ravel())
        selection = None
        blocks = np.unique(indices // _CHUNK_VOXELS) * _CHUNK_VOXELS
    confidence = layer.confidence
    if confidence is not None and (confidence.shape != mask.shape or confidence.dtype != np.uint8
                                   or not confidence.flags.c_contiguous):
        raise ValueError('Confidence must match the editable source grid')
    mask = mask.ravel(); confidence = None if confidence is None else confidence.ravel()
    chunks = []
    for start in blocks:
        start = int(start)
        local = (np.arange(min(_CHUNK_VOXELS, mask.size - start)) if indices is None else
                 np.flatnonzero(selection[start:start + _CHUNK_VOXELS]) if selection is not None else
                 indices[(indices >= start) & (indices < start + _CHUNK_VOXELS)] - start)
        absolute = start + local
        after = target[absolute] if isinstance(target, np.ndarray) else target
        cf_after = target_cf[absolute] if isinstance(target_cf, np.ndarray) else target_cf
        cf_before = confidence[absolute] if confidence is not None else 0
        changed = (mask[absolute] != after) | (cf_before != cf_after)
        local, absolute = local[changed], absolute[changed]
        if not len(local):
            continue
        delta = np.zeros(len(local), dtype=_PATCH_DTYPE)
        delta['index'], delta['before'] = local, mask[absolute]
        delta['after'] = after[changed] if isinstance(after, np.ndarray) else after
        delta['conf_after'] = cf_after[changed] if isinstance(cf_after, np.ndarray) else cf_after
        if confidence is not None:
            delta['conf_before'] = confidence[absolute]
        chunks.append(MaskChunk(start, len(delta), zlib.compress(delta.tobytes(), level=1)))
    # 手工空笔画不能只为了设置 modified 而生成一步；显式采用 AI 则会变更版本来源。
    if not chunks and indices is not None:
        return None
    if (not chunks and layer.provenance == provenance
            and (confidence is not None) == has_target_confidence):
        return None
    return EditCommand(series_uid, record.source_binding['digest'], deepcopy(record.geometry_binding),
                       tuple(cursor or record.cursor), description, layer_id=layer.layer_id,
                       chunks=tuple(chunks), confidence_before_present=confidence is not None,
                       confidence_after_present=has_target_confidence,
                       provenance_before=deepcopy(layer.provenance), provenance_after=deepcopy(provenance))


def add_ai_result(document, series_uid, mask, confidence, provenance, *, kind='organ'):
    record = _bound_record(document, series_uid)
    mask = np.asarray(mask)
    if (mask.dtype != np.uint8 or mask.shape != record.working_mask.shape
            or kind not in ('organ', 'lesion')):
        raise ValueError('AI result must use the verified source label grid')
    if confidence is not None and (confidence.dtype != np.uint8 or confidence.shape != mask.shape):
        raise ValueError('AI confidence must match the source label grid')
    json.dumps(provenance, allow_nan=False)
    mask = mask.copy(); mask.flags.writeable = False
    confidence = None if confidence is None else confidence.copy()
    if confidence is not None:
        confidence.flags.writeable = False
    version = f'ai-{uuid.uuid4().hex}'
    record.layers[version] = AnnotationLayer(version, mask, confidence, kind, True,
                                             deepcopy(provenance))
    document.revision += 1
    document.notify_changed()
    return version


def adopt_ai_command(document, series_uid, version, *, layer_id=None, cursor=None):
    record = _bound_record(document, series_uid)
    original = record.layers.get(version)
    working = record.layers[layer_id or record.active_layer_id]
    if original is None or not original.readonly or original.kind != working.kind:
        raise ValueError('AI version must match the selected working layer kind')
    provenance = {'origin': 'ai', 'ai_version': version, 'modified': False}
    return _mask_change(record, series_uid, working, None, original.mask,
                        original.confidence if original.confidence is not None else 0,
                        original.confidence is not None, provenance, cursor, 'Adopt AI version')


def replace_mask_command(document, series_uid, mask, confidence, *, annotations=None,
                         cursor=None, description='Replace working result', layer_id=None):
    from dataclasses import replace

    record = _bound_record(document, series_uid)
    layer = record.layers[layer_id or record.active_layer_id]
    command = _mask_change(record, series_uid, layer, None, mask,
                           confidence if confidence is not None else 0, confidence is not None,
                           {**layer.provenance, 'modified': True}, cursor, description)
    if annotations is not None:
        annotation = annotations_command(document, series_uid, annotations,
                                          cursor=cursor, description=description)
        if annotation is not None:
            command = (annotation if command is None else
                       replace(command, annotations_before=annotation.annotations_before,
                               annotations_after=annotation.annotations_after))
    return command


def annotations_command(document, series_uid, annotations, *, cursor=None, description='Annotations'):
    record = _bound_record(document, series_uid)
    # 入口排除 Qt 对象、NaN 等不可持久化内容；具体对象形状由交互/工程解码入口检查。
    json.dumps(annotations, allow_nan=False)
    if record.annotations == annotations:
        return None
    return EditCommand(series_uid, record.source_binding['digest'], deepcopy(record.geometry_binding),
                       tuple(cursor or record.cursor), description,
                       annotations_before=deepcopy(record.annotations),
                       annotations_after=deepcopy(annotations))


def create_lesion_command(document, series_uid, *, cursor=None,
                          reference_series_uid=None, reference_layer_id=None):
    record = _bound_record(document, series_uid)
    identity = uuid.uuid4().hex
    provenance = {'origin': 'manual', 'modified': False}
    description = 'Create lesion'
    if reference_series_uid is not None or reference_layer_id is not None:
        if reference_series_uid == series_uid or reference_series_uid is None or reference_layer_id is None:
            raise ValueError('Link a lesion from another connected series in this Study')
        reference = _bound_record(document, reference_series_uid)
        layer = reference.layers.get(reference_layer_id)
        if layer is None or layer.readonly or layer.kind != 'lesion' or not layer.lesion_id:
            raise ValueError('Reference must be an editable lesion instance')
        identity = layer.lesion_id
        if any(item.lesion_id == identity for item in record.layers.values()):
            raise ValueError('This lesion already has a layer in the current series')
        # 只关联实例身份；空间范围留在各来源网格，分类来源也不能跨序列冒用。
        provenance['linked_from'] = {'series_uid': reference_series_uid, 'layer_id': reference_layer_id}
        description = 'Link lesion from reference series'
    return EditCommand(series_uid, record.source_binding['digest'], deepcopy(record.geometry_binding),
        tuple(cursor or record.cursor), description, created_layer={
            'layer_id': f'lesion-{identity}', 'lesion_id': identity,
            'previous_active': record.active_layer_id, 'provenance': provenance})
