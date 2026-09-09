"""同检查三维序列定位/刚性配准；LPS 变换和来源绑定独立于 Qt。"""

from __future__ import annotations

import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone

import numpy as np
from scipy.ndimage import map_coordinates

from mpr_geometry import project_annotation


@dataclass(frozen=True)
class RegistrationResult:
    moving_sid: str
    fixed_sid: str
    moving_digest: str
    fixed_digest: str
    moving_geometry: dict
    fixed_geometry: dict
    moving_to_fixed_lps: tuple
    status: str
    method: str
    quality: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    result_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self):
        value = asdict(self)
        value['moving_to_fixed_lps'] = [list(row) for row in self.moving_to_fixed_lps]
        return value

    @classmethod
    def from_dict(cls, value):
        values = deepcopy(value)
        values['moving_to_fixed_lps'] = tuple(tuple(float(x) for x in row) for row in _rigid_matrix(values['moving_to_fixed_lps']))
        result = cls(**values)
        if (result.status not in ('metadata', 'candidate', 'reviewed', 'landmarks')
                or result.moving_sid == result.fixed_sid or not result.result_id
                or not isinstance(result.quality, dict) or not isinstance(result.parameters, dict)):
            raise ValueError('Invalid registration result')
        datetime.fromisoformat(result.created_at)
        return result


def _rigid_matrix(matrix):
    matrix = np.asarray(matrix, float)
    if (matrix.shape != (4, 4) or not np.isfinite(matrix).all()
            or not np.allclose(matrix[3], [0, 0, 0, 1])
            or not np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-5)
            or not np.isclose(np.linalg.det(matrix[:3, :3]), 1., atol=1e-5)):
        raise ValueError('Expected a finite proper rigid LPS transform')
    return matrix


def _require_pair(moving, fixed):
    if (not moving.source_binding or not fixed.source_binding or moving.affine is None or fixed.affine is None
            or moving.study_uid != fixed.study_uid or moving.series_uid == fixed.series_uid):
        raise ValueError('Two distinct, source-bound spatial series in the same Study are required')


def _frame_of_reference(source):
    values = {str(getattr(ds, 'FrameOfReferenceUID', '') or '') for ds in source.datasets}
    return next(iter(values)) if len(values) == 1 and '' not in values else None


def _points(matrix, points):
    points = np.asarray(points, float)
    if points.shape[-1:] != (3,) or not np.isfinite(points).all():
        raise ValueError('Finite three-dimensional points are required')
    return np.einsum('ij,...j->...i', matrix[:3, :3], points) + matrix[:3, 3]


def _overlap(moving, fixed, matrix):
    fractions = []
    for source, target, transform in ((moving, fixed, matrix), (fixed, moving, np.linalg.inv(matrix))):
        axes = [np.linspace(0, size - 1, min(size, 11)) for size in source.volume.shape]
        zyx = np.stack(np.meshgrid(*axes, indexing='ij'), axis=-1).reshape(-1, 3)
        xyz = _points(np.linalg.inv(target.affine), _points(transform, _points(source.affine, zyx[:, ::-1])))
        valid = np.all((xyz >= -.5) & (xyz < np.array(target.volume.shape[::-1]) - .5), axis=1)
        fractions.append(float(valid.mean()))
    return min(fractions)


def _result(moving, fixed, matrix, status, method, *, quality=None, parameters=None):
    _require_pair(moving, fixed)
    matrix = _rigid_matrix(matrix)
    return RegistrationResult(moving.series_uid, fixed.series_uid,
        moving.source_binding['digest'], fixed.source_binding['digest'],
        deepcopy(moving.geometry_binding), deepcopy(fixed.geometry_binding),
        tuple(tuple(float(x) for x in row) for row in matrix), status, method,
        quality or {}, parameters or {})


def metadata_link(moving, fixed):
    """同 FrameOfReference 只给出元数据定位，不将它标作已验证图像配准。"""
    _require_pair(moving, fixed)
    reference = _frame_of_reference(moving)
    if reference is None or reference != _frame_of_reference(fixed):
        raise ValueError('No shared, consistent FrameOfReferenceUID; image registration is required')
    overlap = _overlap(moving, fixed, np.eye(4))
    if overlap <= 0:
        raise ValueError('Series have no proven spatial overlap')
    return _result(moving, fixed, np.eye(4), 'metadata', 'DICOM-LPS',
                   quality={'overlap_fraction': overlap}, parameters={'frame_of_reference_uid': reference})


def transform_points(result, points, *, inverse=False):
    matrix = _rigid_matrix(result.moving_to_fixed_lps)
    return _points(np.linalg.inv(matrix) if inverse else matrix, points)


def result_matrix(result, source, target, *, allow_candidate=False):
    """验证身份与空间后返回 source→target，反向使用同一结果的逆矩阵。"""
    _require_pair(source, target)
    if result.status == 'candidate' and not allow_candidate:
        raise ValueError('Registration candidate needs alignment review before linking annotations')
    endpoints = {result.moving_sid: (result.moving_digest, result.moving_geometry),
                 result.fixed_sid: (result.fixed_digest, result.fixed_geometry)}
    for volume in (source, target):
        if endpoints.get(volume.series_uid) != (volume.source_binding['digest'], volume.geometry_binding):
            raise ValueError('Registration source identity or geometry changed')
    if result.status == 'metadata':
        reference = result.parameters.get('frame_of_reference_uid')
        if not reference or any(_frame_of_reference(volume) != reference for volume in (source, target)):
            raise ValueError('Metadata coordinate reference changed')
    matrix = _rigid_matrix(result.moving_to_fixed_lps)
    return matrix if source.series_uid == result.moving_sid else np.linalg.inv(matrix)


def transfer_cursor(source, target, cursor_zyx, result):
    matrix = result_matrix(result, source, target)
    cursor = np.asarray(cursor_zyx, float)
    if cursor.shape != (3,) or not np.all((cursor >= -.5) & (cursor < np.array(source.volume.shape) - .5)):
        return None
    xyz = _points(np.linalg.inv(target.affine), _points(matrix, _points(source.affine, cursor[::-1])))
    if not np.all((xyz >= -.5) & (xyz < np.array(target.volume.shape[::-1]) - .5)):
        return None
    return tuple(int(x) for x in np.floor(xyz + .5)[::-1])


class RegistrationCancelled(ValueError):
    """取消或超时不产生可采用结果。"""


def _registration_image(source, sitk, max_dimension):
    if min(source.volume.shape) < 4:
        raise ValueError('3-D registration requires at least four samples along each source axis')
    steps = np.maximum(1, np.ceil(np.array(source.volume.shape) / max_dimension).astype(int))
    values = source.volume[::steps[0], ::steps[1], ::steps[2]].astype(np.float32)
    low, high = np.percentile(values, [1, 99])
    if high <= low:
        low, high = float(values.min()), float(values.max())
    if not np.isfinite([low, high]).all() or high - low <= 1e-8:
        raise ValueError('Registration requires finite, varying image intensities')
    values = np.clip((values - low) / (high - low), 0, 1)
    spacing = np.linalg.norm(source.affine[:3, :3], axis=0)
    direction = source.affine[:3, :3] / spacing
    if not np.allclose(direction.T @ direction, np.eye(3), atol=1e-5):
        raise ValueError('Rigid registration needs an orthonormal source direction')
    image = sitk.GetImageFromArray(values)
    image.SetOrigin(tuple(source.affine[:3, 3]))
    image.SetSpacing(tuple(spacing * steps[::-1]))
    image.SetDirection(tuple(direction.ravel()))
    return image


def register_rigid_3d(moving, fixed, *, cancelled=None, timeout_seconds=120., max_dimension=128):
    """估计 moving→fixed 的 LPS 三维刚性候选；优化成功不等于解剖对应已验证。"""
    _require_pair(moving, fixed)
    cancelled = cancelled or (lambda: False)
    if cancelled():
        raise RegistrationCancelled('Registration cancelled')
    if not 16 <= max_dimension <= 192 or not 0 < timeout_seconds <= 300:
        raise ValueError('Invalid registration resource budget')
    overlap_before = _overlap(moving, fixed, np.eye(4))
    if overlap_before < .05:
        raise ValueError('Insufficient initial spatial overlap for a safe rigid search')
    try:
        import SimpleITK as sitk
    except ImportError as exc:
        raise ValueError('SimpleITK is unavailable; metadata navigation remains available') from exc
    started = time.monotonic()
    moving_image = _registration_image(moving, sitk, max_dimension)
    fixed_image = _registration_image(fixed, sitk, max_dimension)
    initial = sitk.Euler3DTransform()
    center = fixed_image.TransformContinuousIndexToPhysicalPoint([(size - 1) / 2 for size in fixed_image.GetSize()])
    initial.SetCenter(center)
    registration = sitk.ImageRegistrationMethod()
    registration.SetNumberOfThreads(1)
    registration.SetMetricAsMattesMutualInformation(numberOfHistogramBins=32)
    registration.SetMetricSamplingStrategy(registration.REGULAR)
    registration.SetMetricSamplingPercentage(.3, 17)
    registration.SetInterpolator(sitk.sitkLinear)
    registration.SetOptimizerAsRegularStepGradientDescent(learningRate=2., minStep=.005,
        numberOfIterations=160, relaxationFactor=.5, gradientMagnitudeTolerance=1e-6)
    registration.SetOptimizerScalesFromPhysicalShift()
    registration.SetInitialTransform(initial, inPlace=False)
    shrink = [factor for factor in (4, 2, 1) if min(fixed_image.GetSize()) // factor >= 4
              and min(moving_image.GetSize()) // factor >= 4]
    registration.SetShrinkFactorsPerLevel(shrink)
    registration.SetSmoothingSigmasPerLevel([max(0, factor / 2) if factor > 1 else 0 for factor in shrink])
    registration.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    interrupted = [False]

    def observe():
        if cancelled() or time.monotonic() - started > timeout_seconds:
            interrupted[0] = True; registration.StopRegistration()

    registration.AddCommand(sitk.sitkIterationEvent, observe)
    try:
        # SimpleITK 输出 fixed→moving；只在此处求逆一次，后续始终使用 moving→fixed。
        transform = registration.Execute(fixed_image, moving_image)
    except RuntimeError as exc:
        raise ValueError(f'3-D registration failed: {exc}') from exc
    if interrupted[0] or cancelled() or time.monotonic() - started > timeout_seconds:
        raise RegistrationCancelled('Registration cancelled or time budget exceeded')
    origin = np.array(transform.TransformPoint((0., 0., 0.)))
    forward = np.eye(4); forward[:3, 3] = origin
    forward[:3, :3] = np.column_stack([np.array(transform.TransformPoint(tuple(axis))) - origin for axis in np.eye(3)])
    matrix = _rigid_matrix(np.linalg.inv(forward))
    overlap_after = _overlap(moving, fixed, matrix)
    # 独立全采样度量只作数值健康检查；仍需标志点或人工复核，不能单凭分数接受。
    evaluation = sitk.ImageRegistrationMethod(); evaluation.SetNumberOfThreads(1)
    evaluation.SetMetricAsMattesMutualInformation(32); evaluation.SetInterpolator(sitk.sitkLinear)
    evaluation.SetInitialTransform(initial)
    before = float(evaluation.MetricEvaluate(fixed_image, moving_image))
    evaluation.SetInitialTransform(transform)
    after = float(evaluation.MetricEvaluate(fixed_image, moving_image))
    if cancelled() or time.monotonic() - started > timeout_seconds:
        raise RegistrationCancelled('Registration cancelled or time budget exceeded')
    angle = float(np.rad2deg(np.arccos(np.clip((np.trace(matrix[:3, :3]) - 1) / 2, -1, 1))))
    displacement = float(np.linalg.norm(_points(matrix, center) - center))
    if (not np.isfinite([before, after]).all() or after > before + 1e-5 or overlap_after < .05
            or angle > 30 or displacement > 50):
        raise ValueError('Registration failed quality/overlap/motion checks; source annotations remain unchanged')
    return _result(moving, fixed, matrix, 'candidate', 'SimpleITK-Euler3D-MattesMI',
        quality={'metric_before': before, 'metric_after': after, 'overlap_before': overlap_before,
                 'overlap_fraction': overlap_after, 'angle_degrees': angle, 'center_displacement_mm': displacement,
                 'optimizer_stop': registration.GetOptimizerStopConditionDescription()},
        parameters={'simpleitk_version': sitk.Version_VersionString(), 'max_dimension': max_dimension,
                    'sampling': .3, 'seed': 17, 'threads': 1, 'shrink_factors': shrink,
                    'timeout_seconds': timeout_seconds, 'transform_direction': 'moving_to_fixed_lps'})


def verify_landmarks(result, moving_lps, fixed_lps, *, tolerance_mm=2.5):
    """至少三个非共线独立对应点通过物理误差门后，才能记录为标志点验证结果。"""
    moving, fixed = np.asarray(moving_lps, float), np.asarray(fixed_lps, float)
    if (moving.ndim != 2 or moving.shape != fixed.shape or moving.shape[1:] != (3,) or len(moving) < 3
            or not np.isfinite(moving).all() or not np.isfinite(fixed).all() or not 0 < tolerance_mm <= 10
            or np.linalg.matrix_rank(moving - moving.mean(axis=0)) < 2
            or np.linalg.matrix_rank(fixed - fixed.mean(axis=0)) < 2):
        raise ValueError('At least three finite, non-collinear paired landmarks are required')
    errors = np.linalg.norm(transform_points(result, moving) - fixed, axis=1)
    if float(errors.max()) > tolerance_mm:
        raise ValueError('Landmark error exceeds the accepted tolerance; correspondence remains disabled')
    return replace(result, status='landmarks', result_id=uuid.uuid4().hex, quality={**result.quality,
        'landmarks': {'moving_lps': moving.tolist(), 'fixed_lps': fixed.tolist(),
                      'errors_mm': errors.tolist(), 'tolerance_mm': float(tolerance_mm)}})


def registration_pair(moving_sid, fixed_sid):
    return '|'.join(sorted((moving_sid, fixed_sid)))


def mark_visually_reviewed(result):
    return replace(result, status='reviewed', result_id=uuid.uuid4().hex,
        quality={**result.quality, 'review': {'method': 'visual',
                 'reviewed_at': datetime.now(timezone.utc).isoformat(), 'candidate_id': result.result_id}})


def sample_corresponding_plane(source, target, volume, plane, result, *, labels=False, allow_candidate=False):
    """只生成显示平面，不对来源体积或 mask 做回写。"""
    if volume.shape != source.volume.shape:
        raise ValueError('Overlay volume does not match its source grid')
    matrix = result_matrix(result, source, target, allow_candidate=allow_candidate)
    yy, xx = np.indices(plane.shape)
    lps = (plane.origin[:, None, None] + plane.axes[:, 0, None, None] * xx * plane.spacing[1]
           + plane.axes[:, 1, None, None] * yy * plane.spacing[0])
    xyz = _points(np.linalg.inv(source.affine) @ np.linalg.inv(matrix), np.moveaxis(lps, 0, -1))
    coordinates = np.moveaxis(xyz[..., ::-1], -1, 0)
    valid = np.all((coordinates >= -.5) & (coordinates < np.array(source.volume.shape)[:, None, None] - .5), axis=0)
    sampled = map_coordinates(volume, coordinates, order=0 if labels else 1, mode='nearest', prefilter=False)
    sampled[~valid] = 0
    return sampled


def project_corresponding_annotation(annotation, source, target, plane, result):
    if annotation.get('space', {}).get('kind') != 'patient':
        return None  # 旧二维/all 参考标记没有可跨序列使用的患者坐标。
    matrix = result_matrix(result, source, target)
    shown = deepcopy(annotation); space = shown['space']
    space['points_lps'] = _points(matrix, space['points_lps']).tolist()
    space['origin_lps'] = _points(matrix, space['origin_lps']).tolist()
    space['normal_lps'] = (matrix[:3, :3] @ np.array(space['normal_lps'])).tolist()
    return project_annotation(shown, plane)


def validate_registration_state(registrations, links, records, *, require_connected=False):
    if not isinstance(registrations, dict) or not isinstance(links, dict):
        raise ValueError('Invalid registration state')
    for rid, payload in registrations.items():
        result = RegistrationResult.from_dict(payload)
        if rid != result.result_id or result.method not in ('DICOM-LPS', 'SimpleITK-Euler3D-MattesMI'):
            raise ValueError('Invalid registration identity or method')
        for sid, digest, geometry in ((result.moving_sid, result.moving_digest, result.moving_geometry),
                                      (result.fixed_sid, result.fixed_digest, result.fixed_geometry)):
            record = records.get(sid)
            if (record is None or not record.source_binding or record.source_binding['digest'] != digest
                    or not geometry or record.geometry_binding != geometry
                    or (require_connected and record.source is None)):
                raise ValueError('Registration endpoints are unavailable or no longer match their source geometry')
        if result.status == 'metadata':
            if not result.parameters.get('frame_of_reference_uid') or not np.allclose(result.moving_to_fixed_lps, np.eye(4)):
                raise ValueError('Invalid metadata-only transform')
        elif result.status == 'landmarks':
            landmarks = result.quality['landmarks']
            checked = verify_landmarks(result, landmarks['moving_lps'], landmarks['fixed_lps'],
                                       tolerance_mm=landmarks['tolerance_mm'])
            if not np.allclose(landmarks['errors_mm'], checked.quality['landmarks']['errors_mm']):
                raise ValueError('Stored landmark evidence does not match this transform')
        elif result.status == 'reviewed':
            if result.quality.get('review', {}).get('method') != 'visual':
                raise ValueError('Missing registration review evidence')
            datetime.fromisoformat(result.quality['review']['reviewed_at'])
    for pair, rid in links.items():
        result = RegistrationResult.from_dict(registrations[rid])
        if pair != registration_pair(result.moving_sid, result.fixed_sid) or result.status == 'candidate':
            raise ValueError('Active correspondence must reference an accepted result for this pair')
