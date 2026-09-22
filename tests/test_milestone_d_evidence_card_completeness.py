#!/usr/bin/env python
# =============================================================================
# 里程碑 D 验收（第 3 条）：为每个候选模型记录输入序列要求、预处理、空间变换、
# 版本、来源和输出身份——本轮交付一个只读审计闸门 evidence_card_completeness，
# 并对仓库里两张真实证据卡（BIOMEDPARSE_CARD、VS_SEG_CARD）逐项审计现状。
#
# 不新增运行代码、不修改既有证据卡字段：本轮没有对任一候选模型做新的独立验证，
# 改字段会变成没有依据的"证据已补齐"断言。审计发现的具体缺口见下方打印输出
# 与 docs/AGENT_SYNC.md 的交接记录。
#
# 运行：conda activate dicom_gui && python tests/test_milestone_d_evidence_card_completeness.py
# =============================================================================
import dataclasses
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from tumor_model_admission import (
    BIOMEDPARSE_CARD,
    KCL_VS_SEG_T1_SOURCE_IDENTITY,
    VS_SEG_CARD,
    EvidenceState,
    ModelAdmissionCard,
    ModelSourceIdentity,
    TypeOutputScope,
    evidence_card_completeness,
)

_CHECKS = []


def check(cond, label):
    _CHECKS.append(bool(cond))
    print(('  PASS ' if cond else '  FAIL ') + label)
    if not cond:
        raise AssertionError(label)


def _print_evidence_state_gaps(card):
    """打印字段级审计：哪些 EvidenceState 字段不是 VERIFIED，供人读的"如何补齐"依据。"""
    gaps = [(f.name, getattr(card, f.name).value) for f in dataclasses.fields(card)
            if isinstance(getattr(card, f.name), EvidenceState)
            and getattr(card, f.name) is not EvidenceState.VERIFIED]
    print(f'  {card.model_id} 非 VERIFIED 字段（{len(gaps)} 项）：')
    for name, state in gaps:
        print(f'    - {name} = {state}')


def test_real_cards_audit():
    print('[evidence_card_completeness：仓库里两张真实证据卡的现状审计]')
    _print_evidence_state_gaps(BIOMEDPARSE_CARD)
    _print_evidence_state_gaps(VS_SEG_CARD)

    biomedparse = evidence_card_completeness(BIOMEDPARSE_CARD)
    check(not biomedparse.admitted, 'BiomedParse 证据卡当前记录不完整（审计如实报告，不代表已阻止其他准入）')
    check(set(biomedparse.failed_gates) == {'preprocessing', 'spatial_transform', 'source'},
          f'BiomedParse 缺口恰好是 source_identity 完全缺失牵连的三类（实际: {biomedparse.failed_gates}）')

    vs_seg = evidence_card_completeness(VS_SEG_CARD)
    check(vs_seg.admitted and vs_seg.failed_gates == (),
          'VS-SEG 证据卡六类记录（输入序列/预处理/空间变换/版本/来源/输出身份）齐备，'
          '哪怕权重/输入契约/CPU 预算仍是 pending 而不能执行——记录完整和获准执行是两件事')

    check(KCL_VS_SEG_T1_SOURCE_IDENTITY.official_test_transforms
          and KCL_VS_SEG_T1_SOURCE_IDENTITY.sliding_window,
          'VS-SEG 的预处理/空间变换记录来自真实的 source_identity 常量，不是本轮补造')
    check(BIOMEDPARSE_CARD.source_identity is None,
          'BiomedParse 至今没有任何 ModelSourceIdentity 记录——这是恢复以来的既有状态，本轮未补造')


def _fully_evidenced_card():
    identity = ModelSourceIdentity(
        upstream_repository='https://example.invalid/synthetic-repo',
        code_commit='0' * 40, code_license='Apache-2.0',
        weights_doi='10.0000/synthetic', weights_file='synthetic.pt',
        weights_file_size=1, weights_file_md5='0' * 32, weights_sha256='0' * 64,
        weights_license='CC-BY-4.0', upstream_requirements_digest='0' * 64,
        official_input_filename='synthetic.nii.gz',
        official_test_transforms=('LoadNiftid',), sliding_window=(1, 1, 1),
        official_device='cpu',
    )
    return ModelAdmissionCard(
        model_id='synthetic-audit-card', version='1.0', role='candidate-for-review',
        task='synthetic task', anatomy='brain', modality='MRI', required_sequences=('T1',),
        output_scope='conditional candidate mask', type_scope=TypeOutputScope.NO_PREDICTION,
        weights=EvidenceState.PENDING, code=EvidenceState.PENDING, license=EvidenceState.PENDING,
        input_contract=EvidenceState.PENDING, patient_validation=EvidenceState.NOT_ESTABLISHED,
        negative_validation=EvidenceState.NOT_ESTABLISHED, ood_rejection=EvidenceState.NOT_ESTABLISHED,
        cpu_budget=EvidenceState.PENDING, task_compatibility=EvidenceState.PENDING,
        type_region_binding=EvidenceState.NOT_ESTABLISHED,
        automatic_execution=False, product_execution=False, source_identity=identity)


def test_completeness_is_about_records_not_execution_readiness():
    print('[evidence_card_completeness：审计记录完整性，与是否获准执行无关]')
    card = _fully_evidenced_card()
    decision = evidence_card_completeness(card)
    check(decision.admitted,
          '六类记录齐备时审计通过——即使 weights/code/license/input_contract/cpu_budget/'
          'task_compatibility 全部只是 pending（离获准执行还很远）')

    for field, blank in (('required_sequences', ()), ('modality', '')):
        broken = dataclasses.replace(card, **{field: blank})
        check('input_sequence_requirements' in evidence_card_completeness(broken).failed_gates,
              f'去掉 {field} 后审计报告缺输入序列要求')

    no_source = dataclasses.replace(card, source_identity=None)
    decision_no_source = evidence_card_completeness(no_source)
    check({'preprocessing', 'spatial_transform', 'source'} <= set(decision_no_source.failed_gates),
          '整个 source_identity 缺失时，来源/预处理/空间变换三类记录一起缺失（不是各自独立巧合）')

    no_repo = dataclasses.replace(card, source_identity=dataclasses.replace(
        card.source_identity, upstream_repository=''))
    check('source' in evidence_card_completeness(no_repo).failed_gates
          and 'preprocessing' not in evidence_card_completeness(no_repo).failed_gates,
          '只去掉来源仓库地址时只缺"来源"这一类，预处理/空间变换记录本身仍完整')

    no_transforms = dataclasses.replace(card, source_identity=dataclasses.replace(
        card.source_identity, official_test_transforms=()))
    check('preprocessing' in evidence_card_completeness(no_transforms).failed_gates
          and 'source' not in evidence_card_completeness(no_transforms).failed_gates,
          '只去掉预处理 transform 链时只缺"预处理"这一类')

    no_window = dataclasses.replace(card, source_identity=dataclasses.replace(
        card.source_identity, sliding_window=()))
    check('spatial_transform' in evidence_card_completeness(no_window).failed_gates,
          '只去掉滑窗尺寸时缺"空间变换"这一类')

    no_version = dataclasses.replace(card, version='')
    check('version' in evidence_card_completeness(no_version).failed_gates,
          '版本号为空时缺"版本"这一类')

    bad_scope = dataclasses.replace(card, output_scope='')
    check('output_identity' in evidence_card_completeness(bad_scope).failed_gates,
          '输出范围描述为空时缺"输出身份"这一类')


def main():
    test_real_cards_audit()
    test_completeness_is_about_records_not_execution_readiness()
    total, passed = len(_CHECKS), sum(_CHECKS)
    print(f'\n{passed}/{total} 项通过')
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
