"""完整检查工程的单文件保存与恢复；不含 Qt、pickle 或原始 DICOM。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
import uuid
import zipfile
import zlib
from copy import copy, deepcopy
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np

from annotation_state import AnnotationLayer, EditCommand, EditHistory, MaskChunk
from mpr_geometry import annotation_points
from series_registration import validate_registration_state
from study_data import SeriesRecord, StudyDocument


class ProjectError(ValueError):
    """工程未通过校验；调用者不得用局部文档覆盖原件。"""


class HistoryRecoveryRequired(ProjectError):
    """最终状态有效但历史失败；可由用户明确选择独立恢复副本。"""


@dataclass(frozen=True)
class ProjectLimits:
    max_metadata_bytes: int = 16 * 1024**2
    max_member_bytes: int = 512 * 1024**2
    max_total_bytes: int = 2 * 1024**3
    max_voxels: int = 512 * 1024**2
    max_members: int = 100000


@dataclass(frozen=True)
class ProjectSnapshot:
    manifest: dict
    arrays: dict
    commands: tuple
    sources: dict


@dataclass(frozen=True)
class SaveReceipt:
    document_id: str
    revision: int
    path: str
    saved_at: str


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _annotations_json(annotations):
    # JSON 的键只有字符串；序列化时固定切片键，读回时恢复 int，避免 Undo 边界失配。
    return {str(key): deepcopy(value) for key, value in annotations.items()}


def _annotations_restore(value):
    if not isinstance(value, dict):
        raise ProjectError('Invalid annotations')
    return {int(key) if key.isdecimal() else key: annos for key, annos in value.items()}


def _valid_hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _validate_binding(binding, geometry, study_uid, sid, limits):
    if not isinstance(binding, dict):
        raise ProjectError('Missing source binding')
    shape = binding.get('shape')
    if (binding.get('schema') != 'dicom-source-v1' or binding.get('study_uid') != study_uid
            or binding.get('series_uid') != sid or not isinstance(sid, str) or not sid
            or binding.get('array_order') != 'zyx' or binding.get('modality') not in ('CT', 'MR')
            or binding.get('unit') not in ('HU', 'stored')
            or (binding.get('unit') == 'HU' and binding.get('modality') != 'CT')
            or not isinstance(shape, (list, tuple)) or len(shape) != 3
            or any(type(size) is not int or size <= 0 for size in shape)
            or np.prod(shape, dtype=object) > limits.max_voxels):
        raise ProjectError('Invalid source grid binding')
    payload = {key: value for key, value in binding.items() if key != 'digest'}
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    frames = binding.get('frames', [])
    if (binding.get('digest') != _hash(raw) or not isinstance(frames, list) or len(frames) != shape[0]
            or len({frame.get('sop') for frame in frames}) != len(frames)):
        raise ProjectError('Source digest or ordered frame identity failed')
    for frame in frames:
        dtype = np.dtype(frame['dtype'])
        if (not isinstance(frame['sop'], str) or not frame['sop'] or not _valid_hash(frame['pixels'])
                or dtype.kind not in 'iu' or dtype.itemsize > 8):
            raise ProjectError('Invalid source frame identity')
    if geometry is not None:
        affine = np.asarray(geometry['affine_lps'], dtype=float)
        if (geometry.get('schema') != 'dicom-space-v1' or not _valid_hash(geometry.get('fingerprint'))
                or affine.shape != (4, 4) or not np.isfinite(affine).all()
                or not np.allclose(affine[3], [0, 0, 0, 1])
                or abs(np.linalg.det(affine[:3, :3])) < 1e-12):
            raise ProjectError('Invalid patient-space geometry binding')
    return tuple(shape)


def _validate_annotations(annotations, shape, geometry):
    seen = set()
    for key, objects in annotations.items():
        if (key not in ('all', 'objects') and (type(key) is not int or not 0 <= key < shape[0])) or not isinstance(objects, list):
            raise ProjectError('Invalid annotation slice/group')
        for annotation in objects:
            aid = annotation['id']
            if not isinstance(aid, str) or not aid or aid in seen:
                raise ProjectError('Invalid or duplicate annotation identity')
            seen.add(aid); points = annotation_points(annotation)
            space = annotation.get('space')
            if space is None:
                if key == 'objects':
                    raise ProjectError('Patient annotation has no spatial binding')
                continue  # 旧局部/all 对象仍保留来源切片语义。
            if space['schema'] != 1 or space['plane'] not in (0, 1, 2):
                raise ProjectError('Invalid annotation plane')
            if space['kind'] == 'source':
                if (space['plane'] != 0 or type(space['slice']) is not int
                        or not 0 <= space['slice'] < shape[0] or type(space['reference_all']) is not bool):
                    raise ProjectError('Invalid source annotation coordinates')
            elif space['kind'] == 'patient' and geometry is not None:
                lps, zyx = np.asarray(space['points_lps'], float), np.asarray(space['points_zyx'], float)
                origin, normal = np.asarray(space['origin_lps'], float), np.asarray(space['normal_lps'], float)
                spacing = np.asarray(space['spacing'], float)
                affine = np.asarray(geometry['affine_lps'], float)
                if (lps.shape != (len(points), 3) or zyx.shape != lps.shape or origin.shape != (3,)
                        or normal.shape != (3,) or spacing.shape != (2,)
                        or not all(np.isfinite(a).all() for a in (lps, zyx, origin, normal, spacing))
                        or not np.all(spacing > 0) or not np.isclose(np.linalg.norm(normal), 1)
                        or not np.allclose(zyx[:, ::-1] @ affine[:3, :3].T + affine[:3, 3], lps, atol=1e-5)
                        or not np.allclose((lps - origin) @ normal, 0, atol=1e-5)):
                    raise ProjectError('Annotation patient/source coordinates disagree')
            else:
                raise ProjectError('Annotation has no valid patient-space proof')


def _validate_layer_metadata(layers):
    for layer in layers.values():
        if (type(layer.readonly) is not bool or not isinstance(layer.layer_id, str) or not layer.layer_id
                or layer.kind not in ('organ', 'lesion') or not isinstance(layer.provenance, dict)
                or (layer.kind == 'lesion' and not layer.readonly and not isinstance(layer.lesion_id, str))):
            raise ProjectError('Invalid annotation layer metadata')
        ai_version = layer.provenance.get('ai_version')
        if ai_version is not None:
            original = layers.get(ai_version)
            if original is None or not original.readonly or original.kind != layer.kind:
                raise ProjectError('Working result refers to an unavailable AI version')


def _read_array(nested, key, shape, limits):
    """在分配数组前读并验证 NPY 头，阻止声明大 shape、小 payload 或对象 dtype。"""
    name = f'{key}.npy'; info = nested.getinfo(name)
    size = int(np.prod(shape, dtype=object))
    if info.file_size > min(limits.max_member_bytes, size + 8192):
        raise ProjectError('NPY payload exceeds the bound grid')
    with nested.open(info) as stream:
        version = np.lib.format.read_magic(stream)
        if version not in ((1, 0), (2, 0)):
            raise ProjectError('Unsupported NPY header version')
        reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
        saved_shape, fortran, dtype = reader(stream, max_header_size=8192)
        if saved_shape != shape or fortran or dtype != np.uint8:
            raise ProjectError('NPY labels must be C-order uint8 on the bound grid')
        data = stream.read(size + 1)
        if len(data) != size:
            raise ProjectError('Truncated or oversized NPY payload')
    return np.frombuffer(data, np.uint8).reshape(shape).copy()


def capture_project_snapshot(document):
    """仅在文档拥有者线程调用；冻结数组共享给 worker，后续编辑按需复制工作层。"""
    if not document.study_uid or not document.series:
        raise ProjectError('A project requires a bound Study and source series')
    manifest = {'schema': 1, 'document_id': document.document_id, 'study_uid': document.study_uid,
                'revision': document.revision, 'series': [], 'recovery': deepcopy(document.recovery),
                'registrations': deepcopy(document.registrations), 'registration_links': deepcopy(document.registration_links)}
    validate_registration_state(document.registrations, document.registration_links, document.series)
    arrays = {}
    for sid, record in document.series.items():
        if not record.source_binding:
            # 尚未建立身份的纯阅片暂存不属于工程；已标内容绝不能借此被省略。
            transient = (record.source is not None and record.source.source_binding is None
                and not any(command.series_uid == sid for command in document.history.commands)
                and not any(record.annotations.values()) and not record.statistics
                and set(record.layers) == {'working-organs', 'working-manual'}
                and all(not layer.readonly and layer.confidence is None and layer.mask is not None
                        and not layer.mask.any() and not layer.provenance.get('modified')
                        and layer.provenance.get('origin') in ('empty', 'manual')
                        for layer in record.layers.values()))
            if transient:
                continue
            raise ProjectError('Source identity is unavailable for annotated data; project cannot be safely restored')
        member = f'series/{len(manifest["series"])}.npz'
        meta = {'series_uid': sid, 'source_binding': deepcopy(record.source_binding),
                'geometry_binding': deepcopy(record.geometry_binding), 'active_layer_id': record.active_layer_id,
                'annotations': _annotations_json(record.annotations), 'cursor': list(record.cursor),
                'ai_status': deepcopy(record.ai_status), 'layers': [], 'file': member,
                'statistics': deepcopy(record.statistics)}
        payload = {}
        shape = _validate_binding(record.source_binding, record.geometry_binding, document.study_uid, sid, ProjectLimits())
        _validate_annotations(record.annotations, shape, record.geometry_binding)
        _validate_layer_metadata(record.layers)
        for j, layer in enumerate(record.layers.values()):
            layer_meta = {'layer_id': layer.layer_id, 'kind': layer.kind, 'readonly': layer.readonly,
                          'provenance': deepcopy(layer.provenance), 'lesion_id': layer.lesion_id,
                          'mask_key': f'm{j}', 'confidence_key': f'c{j}' if layer.confidence is not None else None}
            for key, value in ((f'm{j}', layer.mask), (f'c{j}', layer.confidence)):
                if value is not None:
                    if value.dtype != np.uint8 or value.shape != shape:
                        raise ProjectError('Labels/confidence must be uint8 on the bound source grid')
                    value.flags.writeable = False
                    frozen = value.view(); frozen.flags.writeable = False
                    payload[key] = frozen
            meta['layers'].append(layer_meta)
        manifest['series'].append(meta); arrays[member] = payload
    if not manifest['series']:
        raise ProjectError('Read-only unbound images cannot form a restorable project')
    _json_bytes(manifest)
    return ProjectSnapshot(manifest, arrays, tuple(deepcopy(document.history.commands)),
                           {sid: record.source for sid, record in document.series.items()})


def _encode_history(commands):
    encoded, blobs = [], {}
    if len(commands) > 20:
        raise ProjectError('History exceeds the agreed 20 operations')
    for index, command in enumerate(commands):
        item = {field.name: deepcopy(getattr(command, field.name))
                for field in fields(EditCommand) if field.name != 'chunks'}
        for name in ('annotations_before', 'annotations_after'):
            if item[name] is not None:
                item[name] = _annotations_json(item[name])
        item['chunks'] = []
        for j, chunk in enumerate(command.chunks):
            member = f'history/{index}-{j}.bin'
            blobs[member] = chunk.data
            item['chunks'].append({'file': member, 'sha256': _hash(chunk.data),
                                   'start': chunk.start, 'count': chunk.count})
        encoded.append(item)
    return _json_bytes({'schema': 1, 'commands': encoded}), blobs


_SUMMARY_FIELDS = ('series_uid', 'layer_id', 'lesion_id', 'kind', 'readonly', 'label_id', 'voxel_count',
                   'range_zyx', 'volume_ml', 'mean_hu', 'sd_hu', 'min_hu', 'max_hu',
                   'type_prediction', 'type_status', 'type_result_version', 'modified', 'provenance',
                   'source_connected', 'statistics_status', 'statistics_computed_at', 'saved_at', 'revision')


def _label_statistics(mask, source):
    """按来源块累计范围与 HU；不为大病灶分配整卷 argwhere 坐标矩阵。"""
    labels, stats = mask.ravel(), {}
    hu = source.volume.ravel() if source is not None and source.geometry.hu_calibrated else None
    for start in range(0, labels.size, 262144):
        block = labels[start:start + 262144]
        for label in np.unique(block):
            if label == 0:
                continue
            indices = np.flatnonzero(block == label) + start
            coords = np.asarray(np.unravel_index(indices, mask.shape))
            count = len(indices)
            current = stats.setdefault(int(label), {'count': 0, 'lo': np.array(mask.shape), 'hi': np.zeros(3, int),
                                                     'sum': 0., 'sum2': 0., 'min': float('inf'), 'max': float('-inf')})
            current['count'] += count
            current['lo'] = np.minimum(current['lo'], coords.min(axis=1))
            current['hi'] = np.maximum(current['hi'], coords.max(axis=1))
            if hu is not None:
                values = hu[indices].astype(np.float64)
                current['sum'] += float(values.sum()); current['sum2'] += float(np.dot(values, values))
                current['min'] = min(current['min'], float(values.min()))
                current['max'] = max(current['max'], float(values.max()))
    result = []
    for label, stat in sorted(stats.items()):
        count = stat['count']
        row = {'label_id': label, 'voxel_count': count,
               'range_zyx': [stat['lo'].tolist(), stat['hi'].tolist()], 'volume_ml': None,
               'mean_hu': None, 'sd_hu': None, 'min_hu': None, 'max_hu': None}
        if source is not None and source.affine is not None:
            row['volume_ml'] = count * abs(float(np.linalg.det(source.affine[:3, :3]))) / 1000
        if hu is not None:
            mean = stat['sum'] / count
            row.update(mean_hu=mean, sd_hu=float(np.sqrt(max(0., stat['sum2'] / count - mean**2))),
                       min_hu=stat['min'], max_hu=stat['max'])
        result.append(row)
    return result or [{'label_id': 0, 'voxel_count': 0, 'range_zyx': [], 'volume_ml': 0. if source and source.affine is not None else None,
                      'mean_hu': None, 'sd_hu': None, 'min_hu': None, 'max_hu': None}]


def _validate_recovery(recovery):
    if recovery is None:
        return
    if (not isinstance(recovery, dict) or not isinstance(recovery.get('source_path'), str)
            or not recovery['source_path'] or not _valid_hash(recovery.get('source_sha256'))
            or not isinstance(recovery.get('protected_paths'), list)
            or not all(isinstance(path, str) and path for path in recovery['protected_paths'])
            or recovery['source_path'] not in recovery['protected_paths']
            or not isinstance(recovery.get('reason'), str) or not recovery['reason']):
        raise ProjectError('Invalid recovery provenance or protected source paths')
    datetime.fromisoformat(recovery['created_at'])


def _validate_statistics(meta):
    layers = {layer['layer_id']: layer for layer in meta['layers']}
    shape = meta['source_binding']['shape']; seen = set()
    for row in meta['statistics']:
        if not isinstance(row, dict) or set(row) != set(_SUMMARY_FIELDS):
            raise ProjectError('Invalid statistics fields')
        layer = layers.get(row['layer_id']); label, count = row['label_id'], row['voxel_count']
        if (layer is None or row['series_uid'] != meta['series_uid'] or row['kind'] != layer['kind']
                or row['lesion_id'] != layer['lesion_id'] or type(row['readonly']) is not bool
                or row['readonly'] != layer['readonly'] or type(label) is not int or not 0 <= label <= 255
                or type(count) is not int or not 0 <= count <= np.prod(shape, dtype=object)
                or (row['layer_id'], label) in seen or type(row['source_connected']) is not bool
                or row['statistics_status'] not in ('computed', 'cached', 'source-unavailable')
                or row['type_status'] not in ('unknown', 'predicted') or type(row['modified']) is not bool
                or row['provenance'] != layer['provenance']):
            raise ProjectError('Invalid statistics source/layer reference')
        seen.add((row['layer_id'], label))
        bounds = row['range_zyx']
        if count:
            if (not isinstance(bounds, list) or len(bounds) != 2 or any(len(corner) != 3 for corner in bounds)
                    or any(type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi < size
                           for lo, hi, size in zip(bounds[0], bounds[1], shape, strict=True))):
                raise ProjectError('Invalid statistics source range')
        elif bounds != [] or label != 0:
            raise ProjectError('Invalid empty statistics range')
        for name in ('volume_ml', 'mean_hu', 'sd_hu', 'min_hu', 'max_hu'):
            value = row[name]
            if value is not None and (type(value) not in (int, float) or not np.isfinite(value)):
                raise ProjectError('Invalid quantitative statistics')
        if (meta['source_binding']['unit'] != 'HU' and any(row[key] is not None
                for key in ('mean_hu', 'sd_hu', 'min_hu', 'max_hu'))):
            raise ProjectError('HU statistics have no calibrated source')
        if meta['geometry_binding'] is None and row['volume_ml'] is not None:
            raise ProjectError('Physical volume has no geometry proof')
        if row['type_status'] == 'unknown':
            if row['type_prediction'] is not None or row['type_result_version'] is not None:
                raise ProjectError('Unknown type has fabricated prediction metadata')
        else:
            original = layers.get(row['type_result_version'])
            if (original is None or not original['readonly'] or not isinstance(row['type_prediction'], str)
                    or row['type_prediction'] != original['provenance'].get('type_prediction')):
                raise ProjectError('Tumor prediction is not bound to its result version')
        datetime.fromisoformat(row['saved_at'])
        if row['statistics_computed_at'] is not None:
            datetime.fromisoformat(row['statistics_computed_at'])
    if {lid for lid, _ in seen} != set(layers):
        raise ProjectError('Statistics omit final layers')


def _summary_csv(manifest):
    output = io.StringIO(newline=''); writer = csv.DictWriter(output, fieldnames=_SUMMARY_FIELDS)
    writer.writeheader()
    for meta in manifest['series']:
        _validate_statistics(meta)
        for row in meta['statistics']:
            serialized = dict(row)
            for key in ('range_zyx', 'provenance'):
                serialized[key] = _json_bytes(serialized[key]).decode()
            writer.writerow(serialized)
    return output.getvalue().encode('utf-8')


def _build_summary(snapshot, manifest, saved_at):
    for meta in manifest['series']:
        source = snapshot.sources[meta['series_uid']]
        layer_index = {layer['layer_id']: layer for layer in meta['layers']}
        records = []
        for layer in meta['layers']:
            lid = layer['layer_id']
            cached = [row for row in meta['statistics'] if row['layer_id'] == lid]
            if source is None and cached:
                rows = deepcopy(cached)
                for row in rows:
                    row.update(source_connected=False, statistics_status='cached', saved_at=saved_at,
                               revision=manifest['revision'])
            else:
                rows = _label_statistics(snapshot.arrays[meta['file']][layer['mask_key']], source)
                original = layer if layer['readonly'] else layer_index.get(layer['provenance'].get('ai_version'))
                prediction = original['provenance'].get('type_prediction') if original and layer['kind'] == 'lesion' else None
                prediction = prediction if isinstance(prediction, str) and prediction else None
                for row in rows:
                    row.update(series_uid=meta['series_uid'], layer_id=lid, lesion_id=layer['lesion_id'],
                        kind=layer['kind'], readonly=layer['readonly'], type_prediction=prediction,
                        type_status='predicted' if prediction else 'unknown',
                        type_result_version=original['layer_id'] if prediction else None,
                        modified=bool(layer['provenance'].get('modified')), provenance=layer['provenance'],
                        source_connected=source is not None, statistics_status='computed' if source else 'source-unavailable',
                        statistics_computed_at=saved_at if source else None, saved_at=saved_at, revision=manifest['revision'])
            records.extend(rows)
        meta['statistics'] = records
    return _summary_csv(manifest)


def save_project_snapshot(snapshot, path, *, limits=None):
    """先写完一个完整 ZIP 并 fsync，再一次替换；失败不改旧工程。"""
    path = os.path.abspath(os.fspath(path))
    limits = limits or ProjectLimits()
    if not path.endswith('.miwproj'):
        raise ProjectError('Project filename must end in .miwproj')
    manifest = deepcopy(snapshot.manifest)
    recovery = manifest.get('recovery')
    _validate_recovery(recovery)
    arrays = [array for payload in snapshot.arrays.values() for array in payload.values()]
    if (sum(array.nbytes + 8192 for array in arrays) > limits.max_total_bytes
            or any(array.nbytes + 8192 > limits.max_member_bytes or array.size > limits.max_voxels for array in arrays)
            or len(_json_bytes(manifest)) > limits.max_metadata_bytes):
        raise ProjectError('Snapshot exceeds the project restore capacity limits')
    verifier = StudyDocument(manifest['study_uid'], registrations=deepcopy(manifest.get('registrations', {})),
                             registration_links=deepcopy(manifest.get('registration_links', {})))
    for meta in manifest['series']:
        payload = snapshot.arrays[meta['file']]
        record = SeriesRecord(None, meta['source_binding'], meta['geometry_binding'], np.empty((0, 0, 0), np.uint8),
                              annotations=_annotations_restore(meta['annotations']), cursor=meta['cursor'])
        record.layers = {layer['layer_id']: AnnotationLayer(layer['layer_id'], payload[layer['mask_key']],
            payload[layer['confidence_key']] if layer['confidence_key'] else None,
            layer['kind'], layer['readonly'], layer['provenance'], layer['lesion_id']) for layer in meta['layers']}
        record.active_layer_id = meta['active_layer_id']
        verifier.series[meta['series_uid']] = record
    try:
        _validate_history_commands(snapshot.commands, verifier, limits)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, zlib.error) as exc:
        raise ProjectError(f'Snapshot history cannot be restored: {exc}') from exc
    if recovery and any(os.path.realpath(path) == os.path.realpath(protected)
                        for protected in recovery['protected_paths']):
        raise ProjectError('A recovery copy cannot overwrite its protected source project')
    saved_at = datetime.now(timezone.utc).isoformat()
    manifest['saved_at'] = saved_at
    history, blobs = _encode_history(snapshot.commands)
    if len(history) > limits.max_metadata_bytes or any(len(blob) > limits.max_member_bytes for blob in blobs.values()):
        raise ProjectError('History exceeds the project restore capacity limits')
    manifest['history'] = {'file': 'history.json', 'sha256': _hash(history)}
    summary = _build_summary(snapshot, manifest, saved_at)
    if len(summary) > limits.max_metadata_bytes:
        raise ProjectError('Summary exceeds the project restore capacity limit')
    manifest['summary'] = {'file': 'summary.csv', 'sha256': _hash(summary)}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.miwproj-', suffix='.tmp', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w+b') as output:
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as package:
                for record in manifest['series']:
                    # 内层 NPZ 压缩，外层 ZIP 不重复压缩；大包 spool 到临时磁盘而非叠加整卷 bytes。
                    with tempfile.SpooledTemporaryFile(max_size=8 * 1024**2) as spool:
                        np.savez_compressed(spool, **snapshot.arrays[record['file']])
                        spool.seek(0); digest = hashlib.sha256()
                        with package.open(record['file'], 'w', force_zip64=True) as member:
                            while block := spool.read(1024**2):
                                digest.update(block); member.write(block)
                        record['sha256'] = digest.hexdigest()
                package.writestr('history.json', history)
                for name, data in blobs.items():
                    package.writestr(name, data)
                package.writestr('summary.csv', summary)
                raw = _json_bytes(manifest)
                if len(raw) > limits.max_metadata_bytes:
                    raise ProjectError('Manifest exceeds the project restore capacity limit')
                package.writestr('manifest.json', raw)
                package.writestr('manifest.sha256', _hash(raw))
            output.flush(); os.fsync(output.fileno())
        with zipfile.ZipFile(temporary) as package:
            _archive_members(package, limits)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return SaveReceipt(manifest['document_id'], manifest['revision'], path, saved_at)


def _archive_members(package, limits):
    entries = package.infolist(); names = [entry.filename for entry in entries]
    if (len(entries) > limits.max_members or len(set(names)) != len(names)
            or any(name.startswith(('/', '\\')) or '\\' in name or '..' in name.split('/') for name in names)
            or any(entry.file_size > limits.max_member_bytes or entry.flag_bits & 1
                   or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) for entry in entries)
            or sum(entry.file_size for entry in entries) > limits.max_total_bytes):
        raise ProjectError('Invalid, duplicate or oversized archive members')
    return set(names)


def _read_member(package, name, *, limit, digest=None):
    info = package.getinfo(name)
    if info.file_size > limit:
        raise ProjectError(f'Archive member exceeds limit: {name}')
    with package.open(info) as stream:
        data = stream.read(limit + 1)
    if len(data) != info.file_size or len(data) > limit or (digest is not None and _hash(data) != digest):
        raise ProjectError(f'Archive member integrity failed: {name}')
    return data


def _read_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ProjectError('Duplicate JSON keys')
            value[key] = item
        return value

    def invalid_constant(value):
        raise ProjectError(f'Non-finite JSON: {value}')

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def _load_history(package, manifest, doc, limits):
    if manifest['history']['file'] != 'history.json' or not _valid_hash(manifest['history']['sha256']):
        raise ProjectError('Invalid history reference')
    history = _read_json(_read_member(package, 'history.json', limit=limits.max_metadata_bytes,
                                     digest=manifest['history']['sha256']))
    if history['schema'] != 1 or len(history['commands']) > 20:
        raise ProjectError('Invalid history schema or length')
    commands = []
    for item in history['commands']:
        if (sum(chunk['count'] for chunk in item['chunks']) * 8 > limits.max_total_bytes
                or not all(_valid_hash(chunk['sha256']) for chunk in item['chunks'])):
            raise ProjectError('History expansion or digest is invalid')
        chunks = tuple(MaskChunk(chunk['start'], chunk['count'],
            _read_member(package, chunk['file'], limit=limits.max_member_bytes, digest=chunk['sha256']))
            for chunk in item.pop('chunks'))
        for name in ('annotations_before', 'annotations_after'):
            if item[name] is not None:
                item[name] = _annotations_restore(item[name])
        item['cursor'] = tuple(item['cursor'])
        command = EditCommand(**item, chunks=chunks)
        commands.append(command)
    _validate_history_commands(commands, doc, limits)
    return EditHistory(commands)


def _validate_history_commands(commands, doc, limits):
    if len(commands) > 20:
        raise ProjectError('History exceeds the agreed 20 operations')
    operation_ids = set()
    for command in commands:
        if sum(chunk.count for chunk in command.chunks) * 8 > limits.max_total_bytes:
            raise ProjectError('History expansion exceeds the project memory limit')
        record = doc.series.get(command.series_uid)
        if (record is None or command.operation_id in operation_ids or not command.operation_id
                or len(command.cursor) != 3
                or any(type(c) is not int or not 0 <= c < size
                       for c, size in zip(command.cursor, record.source_binding['shape'], strict=True))
                or command.view_plane not in (None, 0, 1, 2)):
            raise ProjectError('Invalid history source, operation identity or cursor')
        for annotation_state in (command.annotations_before, command.annotations_after):
            if annotation_state is not None:
                _validate_annotations(annotation_state, record.source_binding['shape'], record.geometry_binding)
        if (type(command.confidence_before_present) is not bool or type(command.confidence_after_present) is not bool
                or (command.layer_id is None and command.chunks)
                or (command.annotations_before is None) != (command.annotations_after is None)):
            raise ProjectError('Invalid history payload boundary')
        operation_ids.add(command.operation_id)

    # 包内回放只检验持久化边界一致性，不能证明真实来源已连接；临时 source 不返回给 UI。
    verifier = copy(doc); verifier.series = {}
    verifier.registration_links = deepcopy(doc.registration_links)
    for sid, record in doc.series.items():
        candidate = copy(record)
        candidate.source = SimpleNamespace(source_binding=record.source_binding, geometry_binding=record.geometry_binding)
        candidate.layers = {}
        for lid, layer in record.layers.items():
            cloned = copy(layer)
            layer.mask.flags.writeable = False
            cloned.mask = layer.mask.view()
            if layer.confidence is not None:
                layer.confidence.flags.writeable = False
                cloned.confidence = layer.confidence.view()
            candidate.layers[lid] = cloned
        verifier.series[sid] = candidate
    verifier.history = EditHistory(list(commands))
    while verifier.history.commands:
        verifier.undo()


def _recover_document(doc, path, reason):
    with open(path, 'rb') as stream:
        digest = hashlib.sha256()
        while block := stream.read(1024**2):
            digest.update(block)
    protected = list(doc.recovery.get('protected_paths', [])) if doc.recovery else []
    protected.append(os.path.abspath(os.fspath(path)))
    doc.document_id = uuid.uuid4().hex
    name = hashlib.sha256(doc.study_uid.encode()).hexdigest() + f'_recovered_{doc.document_id}.miwproj'
    doc.project_path = os.path.join(os.path.dirname(os.path.abspath(path)), name)
    doc.recovery = {'source_path': os.path.abspath(os.fspath(path)), 'source_sha256': digest.hexdigest(),
                    'protected_paths': protected, 'reason': str(reason),
                    'created_at': datetime.now(timezone.utc).isoformat()}
    doc.history = EditHistory(); doc.revision += 1; doc.saved_revision = -1


def load_project_snapshot(path, *, limits=None, recover_history=False):
    """先完整解码候选；来源保持 offline，须匹配当前 DICOM 后才能编辑。"""
    limits = limits or ProjectLimits()
    try:
        with zipfile.ZipFile(path) as package:
            _archive_members(package, limits)
            raw = _read_member(package, 'manifest.json', limit=limits.max_metadata_bytes)
            expected = _read_member(package, 'manifest.sha256', limit=64).decode('ascii')
            if _hash(raw) != expected:
                raise ProjectError('Manifest integrity failed')
            manifest = _read_json(raw)
            if type(manifest['schema']) is not int or manifest['schema'] != 1:
                raise ProjectError('Unsupported project schema')
            doc = StudyDocument(manifest['study_uid'], document_id=manifest['document_id'],
                                revision=manifest['revision'], saved_revision=manifest['revision'],
                                project_path=os.path.abspath(os.fspath(path)), saved_at=manifest['saved_at'],
                                recovery=manifest.get('recovery'), registrations=manifest.get('registrations', {}),
                                registration_links=manifest.get('registration_links', {}))
            datetime.fromisoformat(doc.saved_at)
            _validate_recovery(doc.recovery)
            if (not isinstance(doc.study_uid, str) or not doc.study_uid or not manifest['series']
                    or not isinstance(doc.document_id, str) or not doc.document_id
                    or type(doc.revision) is not int or doc.revision < 0):
                raise ProjectError('Project has no bound Study/series')
            final_bytes = 0
            for index, meta in enumerate(manifest['series']):
                sid = meta['series_uid']; binding = meta['source_binding']
                shape = _validate_binding(binding, meta['geometry_binding'], doc.study_uid, sid, limits)
                if sid in doc.series or meta['file'] != f'series/{index}.npz':
                    raise ProjectError('Duplicate or invalid series reference')
                if not _valid_hash(meta['sha256']):
                    raise ProjectError('Invalid final layer digest')
                annotations = _annotations_restore(meta['annotations'])
                _validate_annotations(annotations, shape, meta['geometry_binding'])
                if (len(meta['cursor']) != 3 or any(type(c) is not int or not 0 <= c < size
                        for c, size in zip(meta['cursor'], shape, strict=True))):
                    raise ProjectError('Invalid saved cursor')
                payload = _read_member(package, meta['file'], limit=limits.max_member_bytes, digest=meta['sha256'])
                stream = io.BytesIO(payload)
                layers = {}
                with zipfile.ZipFile(stream) as nested:
                    members = _archive_members(nested, limits)
                    expected_keys = [key for layer in meta['layers']
                                     for key in (layer['mask_key'], layer['confidence_key']) if key is not None]
                    if (len(expected_keys) != len(set(expected_keys))
                            or members != {f'{key}.npy' for key in expected_keys}):
                        raise ProjectError('Unreferenced, duplicate or missing NPZ arrays')
                    final_bytes += int(np.prod(shape, dtype=object)) * len(expected_keys)
                    if final_bytes > limits.max_total_bytes:
                        raise ProjectError('Final arrays exceed the project memory limit')
                    for layer in meta['layers']:
                        mask = _read_array(nested, layer['mask_key'], shape, limits)
                        confidence = _read_array(nested, layer['confidence_key'], shape, limits) if layer['confidence_key'] else None
                        if (mask.dtype != np.uint8 or mask.shape != shape
                                or (confidence is not None and (confidence.dtype != np.uint8 or confidence.shape != shape))
                                or layer['layer_id'] in layers or layer['kind'] not in ('organ', 'lesion')):
                            raise ProjectError('Invalid final annotation layer')
                        if layer['readonly']:
                            mask.flags.writeable = False
                            if confidence is not None:
                                confidence.flags.writeable = False
                        layers[layer['layer_id']] = AnnotationLayer(layer['layer_id'], mask, confidence,
                            layer['kind'], layer['readonly'], layer['provenance'], layer['lesion_id'])
                _validate_layer_metadata(layers)
                if (meta['active_layer_id'] not in layers or layers[meta['active_layer_id']].readonly
                        or not {'working-organs', 'working-manual'} <= layers.keys()):
                    raise ProjectError('Invalid working layer reference')
                record = SeriesRecord(None, binding, meta['geometry_binding'], np.empty((0, 0, 0), np.uint8),
                                      annotations=annotations, cursor=meta['cursor'])
                record.layers = layers; record.active_layer_id = meta['active_layer_id']
                record.ai_status = meta['ai_status']; record.visited = True
                record.statistics = meta['statistics']
                doc.series[sid] = record
            validate_registration_state(doc.registrations, doc.registration_links, doc.series)
            if manifest['summary']['file'] != 'summary.csv' or not _valid_hash(manifest['summary']['sha256']):
                raise ProjectError('Invalid summary reference')
            summary = _read_member(package, 'summary.csv', limit=limits.max_metadata_bytes,
                                   digest=manifest['summary']['sha256'])
            if summary != _summary_csv(manifest):
                raise ProjectError('CSV summary does not describe the manifest revision')
            try:
                doc.history = _load_history(package, manifest, doc, limits)
            except (ValueError, KeyError, TypeError, AttributeError, IndexError, zlib.error,
                    zipfile.BadZipFile, EOFError) as exc:
                if not recover_history:
                    raise HistoryRecoveryRequired(f'Final annotations are valid; history failed: {exc}') from exc
                _recover_document(doc, path, exc)
            return doc
    except ProjectError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, OverflowError,
            zipfile.BadZipFile, EOFError, zlib.error) as exc:
        raise ProjectError(f'Project could not be completely restored: {exc}') from exc
