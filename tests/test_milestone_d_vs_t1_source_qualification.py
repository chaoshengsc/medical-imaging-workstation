#!/usr/bin/env python
# =============================================================================
# 里程碑 D 验收（第 1 条）：修复 tumor_model_admission.qualify_vs_t1_source
# 里从恢复起就存在的坏引用（不存在的 series_read_qc 模块 + 不存在的
# SeriesVolume.read_qc 字段），用 VS-SEG-002 / VS-SEG-003 真实 MRI 验证
# fail-closed 行为没有因为去掉这个坏引用而放宽。
#
# 数据来自 Annotation_Projects/recovered_vestibular_schwannoma_cases/（不入库，
# 见 .gitignore），本机不存在时跳过并给出明确原因，不伪造通过。
#
# 运行：conda activate dicom_gui && python tests/test_milestone_d_vs_t1_source_qualification.py
# =============================================================================
import dataclasses
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from study_data import read_series_directory
from tumor_model_admission import qualify_vs_t1_source

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
    source = read_series_directory(dicom_dir).series[0]

    decision = qualify_vs_t1_source(source)
    check(decision.qualified and decision.failed_gates == (),
          f'{case["patient_id"]} 真实合规 VS T1 序列通过 qualify_vs_t1_source（正例，不再 ModuleNotFoundError）')
    check(decision.source_binding is not None
          and decision.source_binding.study_instance_uid == source.study_uid
          and decision.source_binding.series_instance_uid == source.series_uid,
          f'{case["patient_id"]} 通过后返回的 SourceBinding 绑定的是同一 Study/Series')

    not_a_series_volume = qualify_vs_t1_source(object())
    check(not not_a_series_volume.qualified and not_a_series_volume.failed_gates == ('series_volume',),
          f'{case["patient_id"]} 非 SeriesVolume 输入被拒绝（fail-closed 对类型检查仍生效）')

    tampered_binding = dataclasses.replace(
        source, source_binding={**source.source_binding, 'digest': '0' * 64})
    decision_binding = qualify_vs_t1_source(tampered_binding)
    check(not decision_binding.qualified and 'series_rebuild' in decision_binding.failed_gates,
          f'{case["patient_id"]} 篡改 source_binding 摘要后拒绝（来源身份不匹配）')

    bad_affine = source.affine.copy()
    bad_affine.flags.writeable = True
    bad_affine[0, 0] += 1.0
    bad_affine.flags.writeable = False
    tampered_affine = dataclasses.replace(source, affine=bad_affine)
    decision_affine = qualify_vs_t1_source(tampered_affine)
    check(not decision_affine.qualified and 'series_rebuild' in decision_affine.failed_gates,
          f'{case["patient_id"]} 篡改患者空间 affine 后拒绝（几何身份不匹配）')

    tampered_datasets = dataclasses.replace(source, datasets=source.datasets[:-1])
    decision_datasets = qualify_vs_t1_source(tampered_datasets)
    check(not decision_datasets.qualified and 'series_rebuild' in decision_datasets.failed_gates,
          f'{case["patient_id"]} 少一帧的来源数据集后拒绝（帧数/体数据形状不匹配）')

    print(f'{case["patient_id"]} PASS')


def main():
    if not os.path.isfile(_MANIFEST):
        print(f'WARN: 未找到 {_MANIFEST}，跳过里程碑 D VS T1 来源准入测试（本机未恢复该数据）')
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
