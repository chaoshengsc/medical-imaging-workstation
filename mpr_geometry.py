# =============================================================================
# MPR 坐标几何纯计算模块
# 负责：MPR 三平面与 3D 光标 [z,y,x] 之间的坐标换算，以及双序列解剖 z 配准。
# 设计：无任何 Qt/UI 依赖，纯整数/数组运算。把原先散落在 sync_crosshair /
#       _render_clinical_plane / _render_compare 里的同一套坐标约定收拢为单一
#       可信来源（历史上轴向易错，见 BUG J），并可独立单测。
#
# 坐标约定（三平面共用同一个 3D 光标 [z, y, x]）：
#   - Axial    视图 (px,py) → 3D 的 (x=px, y=py)，z 不变
#   - Coronal  视图 (px,py) → 3D 的 (x=px, z=Z-1-py)，y 不变（上 S / 下 I）
#   - Sagittal 视图 (px,py) → 3D 的 (y=px, z=Z-1-py)，x 不变（上 S / 下 I）
# =============================================================================

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import product

import numpy as np
from scipy.ndimage import map_coordinates

from constants import AXIAL, CORONAL, SAGITTAL


def annotation_points(annotation):
    """普通标注的创建平面控制点；ROI 轮廓仅用于跨面求交。"""
    kind = annotation.get('type')
    if kind == 'ruler':
        points = [annotation['p1'], annotation['p2']]
    elif kind == 'path':
        points = annotation['points']
    elif kind == 'roi':
        x, y, width, height = annotation['rect']
        if width <= 0 or height <= 0:
            raise ValueError('ROI must have positive dimensions')
        angles = np.linspace(0, 2 * np.pi, 129)
        points = np.column_stack((x + width / 2 * (1 + np.cos(angles)),
                                  y + height / 2 * (1 + np.sin(angles))))
    else:
        raise ValueError('Unsupported annotation type')
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or not len(points) or not np.all(np.isfinite(points)):
        raise ValueError('Annotation points must be finite coordinate pairs')
    return points


def bind_annotation(annotation, mapping, cursor, plane, *, reference_all=False):
    """在创建时记录空间证明，缺几何或重复参考只保留来源切片，不补造三维对象。"""
    result = deepcopy(annotation)
    result['id'] = str(result['id'])
    points = annotation_points(result)
    space = {'schema': 1, 'plane': int(plane), 'cursor': list(cursor)}
    if mapping is None or reference_all:
        if plane != AXIAL:
            raise ValueError('Source-grid reference requires a source slice')
        space.update(kind='source', slice=int(cursor[0]), reference_all=bool(reference_all))
    else:
        lps = (mapping.origin + (points[:, 0:1] - .5) * mapping.axes[:, 0] * mapping.spacing[1]
               + (points[:, 1:2] - .5) * mapping.axes[:, 1] * mapping.spacing[0])
        source = (lps @ mapping.inverse[:3, :3].T + mapping.inverse[:3, 3])[:, ::-1]
        space.update(kind='patient', points_lps=lps.tolist(), points_zyx=source.tolist(),
                     normal_lps=mapping.axes[:, 2].tolist(),
                     origin_lps=mapping.origin.tolist(), spacing=list(mapping.spacing))
    result['space'] = space
    return result


def project_annotation(annotation, mapping):
    """返回当前患者面中的完整轮廓或真实交点；平行异面不显示。"""
    space = annotation['space']
    if space['kind'] != 'patient' or mapping is None:
        return {'coplanar': False, 'points': []}
    points = np.asarray(space['points_lps'], dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.all(np.isfinite(points)):
        raise ValueError('Patient annotation points must be finite LPS triples')
    local = (points - mapping.origin) @ mapping.axes
    coplanar = bool(np.all(np.abs(local[:, 2]) <= 1e-5))
    if coplanar:
        coords = local[:, :2] / np.array(mapping.spacing[::-1]) + .5
    else:
        hits = []
        for a, b in zip(local[:-1], local[1:], strict=True):
            if abs(a[2]) <= 1e-5:
                hits.append(a[:2])
            if a[2] * b[2] < 0:
                hits.append((a + (b - a) * (-a[2] / (b[2] - a[2])))[:2])
        if abs(local[-1, 2]) <= 1e-5:
            hits.append(local[-1, :2])
        unique = []
        for hit in hits:
            if not any(np.linalg.norm(hit - other) <= 1e-5 for other in unique):
                unique.append(hit)
        coords = (np.asarray(unique) / np.array(mapping.spacing[::-1]) + .5
                  if unique else np.empty((0, 2)))
    return {'coplanar': coplanar, 'points': coords.tolist()}


def stroke_voxels(points, radius, mapping, shape, cursor):
    """Qt 场景边缘坐标 → 来源体素；radius=0 为单体素精修，笔画取集合。"""
    points = np.asarray(points, dtype=float)
    if points.size == 0:
        return np.empty(0, dtype=np.int64)
    if points.ndim != 2 or points.shape[1] != 2 or not np.all(np.isfinite(points)):
        raise ValueError('Stroke points must be finite scene coordinates')
    radius = int(radius)
    if not 0 <= radius <= 40:
        raise ValueError('Unsupported brush radius')
    offsets = [(dx, dy) for dy in range(-radius, radius + 1)
               for dx in range(-radius, radius + 1) if dx * dx + dy * dy <= radius * radius]
    result = set()
    previous = points[0]
    for point in points:
        # 补齐稀疏鼠标 Move 事件之间的轨迹，单击只取一次来源最近体素。
        count = max(1, int(np.ceil(np.max(np.abs(point - previous)) * 2)) + 1)
        for x, y in np.linspace(previous, point, count):
            for dx, dy in offsets:
                if mapping is not None:
                    # QPixmap 像素 i 的中心位于场景 i+.5；纯采样器使用中心索引 i。
                    voxel = mapping.scene_to_voxel(x + dx - .5, y + dy - .5)
                else:
                    voxel = (int(cursor[0]), int(np.floor(y + dy)), int(np.floor(x + dx)))
                    if any(q < 0 or q >= size for q, size in zip(voxel, shape, strict=True)):
                        voxel = None
                if voxel is not None:
                    result.add(int(np.ravel_multi_index(voxel, shape)))
        previous = point
    return np.asarray(sorted(result), dtype=np.int64)


def hover_to_voxel(plane: int, px: int, py: int,
                   cur: tuple[int, int, int],
                   shape: tuple[int, int, int]) -> tuple[int, int, int]:
    """把某平面上的悬停像素 (px,py) 映射为完整 3D 体素 (z,y,x)，非该平面的轴沿用当前
    光标 cur=(z,y,x)，并按 shape=(Z,Y,X) 裁剪到体积范围内。返回 (z,y,x)。"""
    z, y, x = cur
    Z, Y, X = shape
    if plane == AXIAL:
        x, y = px, py
    elif plane == CORONAL:
        x, z = px, Z - 1 - py
    elif plane == SAGITTAL:
        y, z = px, Z - 1 - py
    x = max(0, min(x, X - 1))
    y = max(0, min(y, Y - 1))
    z = max(0, min(z, Z - 1))
    return z, y, x


def voxel_to_crosshair(plane: int, z: int, y: int, x: int,
                       shape: tuple[int, int, int]) -> tuple[int, int]:
    """把 3D 光标 (z,y,x) 投影为某平面上十字准线的 2D 坐标 (cx,cy)。"""
    if plane == CORONAL:
        return x, shape[0] - 1 - z
    if plane == SAGITTAL:
        return y, shape[0] - 1 - z
    return x, y  # AXIAL（含缺省）


def nearest_slice(zpos, target_z: float) -> int:
    """在解剖 z 坐标数组 zpos 中，返回与 target_z 最接近的切片索引（双序列配准）。

    zpos 为空时返回 0 而非让 np.argmin 抛 ValueError：本函数在渲染热路径上被调用，
    崩在这里会让整个对比视图挂掉；退回首层是安全且可见的降级。
    （正常路径下 compare_lab 的守卫已保证 zpos 非空，此处是纵深防御。）
    """
    a = np.asarray(zpos)
    if a.size == 0:
        return 0
    return int(np.argmin(np.abs(a - target_z)))


@dataclass(frozen=True)
class PatientPlane:
    """一个患者解剖平面的像素中心网格；影像、标签及编辑共用同一映射。"""

    source_shape: tuple[int, int, int]
    shape: tuple[int, int]
    spacing: tuple[float, float]
    origin: np.ndarray
    axes: np.ndarray
    affine: np.ndarray
    inverse: np.ndarray

    def scene_to_source(self, x, y):
        point = self.origin + self.axes[:, 0] * x * self.spacing[1] + self.axes[:, 1] * y * self.spacing[0]
        return (self.inverse[:3, :3] @ point + self.inverse[:3, 3])[::-1]

    def scene_to_voxel(self, x, y):
        q = self.scene_to_source(float(x), float(y))
        if (not np.all(np.isfinite(q)) or np.any(q < -0.5)
                or np.any(q >= np.asarray(self.source_shape) - 0.5)):
            return None
        return tuple(int(i) for i in np.floor(q + 0.5))

    def voxel_to_scene(self, zyx):
        point = self.affine[:3, :3] @ np.asarray(zyx)[::-1] + self.affine[:3, 3]
        local = self.axes.T @ (point - self.origin)
        return float(local[0] / self.spacing[1]), float(local[1] / self.spacing[0]), float(local[2])

    def step_normal(self, zyx, increment):
        """导航沿患者平面法向选邻近来源体素；边界限制仅用于导航，不用于编辑。"""
        direction = (self.inverse[:3, :3] @ self.axes[:, 2])[::-1]
        direction /= np.linalg.norm(direction)
        target = np.floor(np.asarray(zyx) + int(increment) * direction + 0.5).astype(int)
        return np.clip(target, 0, np.asarray(self.source_shape) - 1).tolist()

    def source_coordinates(self):
        yy, xx = np.indices(self.shape, dtype=float)
        points = (self.origin[:, None, None]
                  + self.axes[:, 0, None, None] * xx * self.spacing[1]
                  + self.axes[:, 1, None, None] * yy * self.spacing[0])
        return (np.einsum('ij,jhw->ihw', self.inverse[:3, :3], points)
                + self.inverse[:3, 3, None, None])[::-1]

    def sample(self, volume, *, labels=False, fill=0):
        if tuple(volume.shape) != self.source_shape:
            raise ValueError('Volume does not match plane source grid')
        coordinates = self.source_coordinates()
        valid = np.all((coordinates >= -0.5)
                       & (coordinates < np.asarray(self.source_shape)[:, None, None] - 0.5), axis=0)
        # nearest 边界仅服务于合法边缘体素的插值；越过半开体素边界仍强制为空。
        sampled = map_coordinates(volume, coordinates, order=0 if labels else 1,
                                  mode='nearest', prefilter=False)
        sampled[~valid] = fill
        return sampled


def patient_plane(affine, shape, plane, current_zyx) -> PatientPlane:
    """在完整来源包围盒中建立 LPS 解剖平面，不旋转或覆盖来源数组。"""
    affine = np.asarray(affine, dtype=float)
    shape = tuple(int(v) for v in shape)
    if (affine.shape != (4, 4) or not np.all(np.isfinite(affine))
            or not np.allclose(affine[3], (0, 0, 0, 1))
            or len(shape) != 3 or min(shape) < 1):
        raise ValueError('A finite affine and nonempty 3D grid are required')
    inverse = np.linalg.inv(affine)
    basis = {AXIAL: ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
             CORONAL: ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
             SAGITTAL: ((0, 1, 0), (0, 0, -1), (1, 0, 0))}
    if plane not in basis:
        raise ValueError('Unknown anatomical plane')
    axes = np.asarray(basis[plane], dtype=float).T
    corners = np.array(list(product(*[(0, size - 1) for size in shape[::-1]]))).T
    projected = axes.T @ (affine[:3, :3] @ corners + affine[:3, 3, None])
    low, high = projected.min(axis=1), projected.max(axis=1)
    current = affine[:3, :3] @ np.asarray(current_zyx)[::-1] + affine[:3, 3]
    low[2] = float(axes[:, 2] @ current)
    # 沿显示轴移动一个有效来源采样距离；canonical 输入精确退化为旧像素间距。
    dx, dy = 1 / np.linalg.norm(inverse[:3, :3] @ axes[:, :2], axis=0)
    width, height = np.ceil((high[:2] - low[:2]) / [dx, dy] - 1e-9).astype(int) + 1
    return PatientPlane(shape, (int(height), int(width)), (float(dy), float(dx)),
                        axes @ low, axes, affine, inverse)


def patient_plane_cursors(affine, shape, plane):
    """覆盖来源包围盒的患者平面位置；用于复核浏览，不取整成来源数组轴。"""
    center = (np.asarray(shape, float) - 1) / 2
    mapping = patient_plane(affine, shape, plane, center)
    normal = mapping.axes[:, 2]
    corners = np.array(list(product(*[(0, size - 1) for size in shape[::-1]])))
    world = np.einsum('ij,nj->ni', mapping.affine[:3, :3], corners) + mapping.affine[:3, 3]
    positions = world @ normal
    low, high = float(positions.min()), float(positions.max())
    step = 1 / np.linalg.norm(mapping.inverse[:3, :3] @ normal)
    count = max(1, int(np.ceil((high - low) / step - 1e-9)) + 1)
    midpoint = mapping.affine[:3, :3] @ center[::-1] + mapping.affine[:3, 3]
    points = midpoint + (np.linspace(low, high, count) - midpoint @ normal)[:, None] * normal
    # 斜采集包围盒内的平面中心可在来源网格外；采样器裁掉空白，不能夹紧后改变平面。
    return (np.einsum('ij,nj->ni', mapping.inverse[:3, :3], points) + mapping.inverse[:3, 3])[:, ::-1]
