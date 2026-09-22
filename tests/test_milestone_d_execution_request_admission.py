#!/usr/bin/env python
# =============================================================================
# 里程碑 D 验收（第 4 条）：只有权重、输入契约、患者级验证和运行资源均有证据时，
# 才单独提出执行申请。
#
# execution_request_admission 是"能不能提出申请"这一步的闸门，比
# product_execution_admission（"申请能不能被批准"）更窄：不要求 code/license/
# task_compatibility/negative_validation/ood_rejection，也不看
# automatic_execution/product_execution 两个标记。通过这一步只表示达到了
# "可以去问"的最低门槛，不是获准执行、不是获准采用、不是效能声明。
#
# 本仓库两个真实候选（BIOMEDPARSE_CARD、VS_SEG_CARD）目前都达不到这个更低的
# 门槛，因此没有可以现在提出的执行申请——本轮不新增任何执行代码或申请模板。
#
# 运行：conda activate dicom_gui && python tests/test_milestone_d_execution_request_admission.py
# =============================================================================
import os
import sys
from dataclasses import replace

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from tumor_model_admission import (
    BIOMEDPARSE_CARD,
    VS_SEG_CARD,
    EvidenceState,
    ModelAdmissionCard,
    TypeOutputScope,
    execution_request_admission,
    product_execution_admission,
)

_CHECKS = []


def check(cond, label):
    _CHECKS.append(bool(cond))
    print(('  PASS ' if cond else '  FAIL ') + label)
    if not cond:
        raise AssertionError(label)


def _fully_evidenced_card():
    """合成的、假设通过执行申请门槛的证据卡；不对应任何真实可运行模型或权重。"""
    return ModelAdmissionCard(
        model_id='synthetic-request-eligible', version='1.0-test-only',
        role='candidate-for-review', task='synthetic lesion segmentation',
        anatomy='brain', modality='MRI', required_sequences=('T1',),
        output_scope='conditional candidate mask', type_scope=TypeOutputScope.NO_PREDICTION,
        weights=EvidenceState.VERIFIED, code=EvidenceState.PENDING, license=EvidenceState.PENDING,
        input_contract=EvidenceState.VERIFIED, patient_validation=EvidenceState.VERIFIED,
        negative_validation=EvidenceState.NOT_ESTABLISHED, ood_rejection=EvidenceState.NOT_ESTABLISHED,
        cpu_budget=EvidenceState.VERIFIED, task_compatibility=EvidenceState.PENDING,
        type_region_binding=EvidenceState.NOT_ESTABLISHED,
        automatic_execution=False, product_execution=False,
    )


def test_real_candidates_cannot_request_execution_yet():
    print('[execution_request_admission：仓库里两个真实候选目前都不能提出执行申请]')
    for card in (BIOMEDPARSE_CARD, VS_SEG_CARD):
        decision = execution_request_admission(card)
        check(not decision.admitted,
              f'{card.model_id} 缺权重/输入契约/患者级验证/运行资源中至少一项，不能提出执行申请')
        check(set(decision.failed_gates) <= {'weights', 'input_contract',
                                              'patient_validation', 'cpu_budget'},
              f'{card.model_id} 的缺口只落在这四项证据里（实际: {decision.failed_gates}）')
        check(not product_execution_admission(card).admitted,
              f'{card.model_id} 同样通不过更严格的执行批准门槛（两层门槛一致拒绝，不冲突）')


def test_request_gate_is_narrower_than_grant_gate():
    print('[execution_request_admission：比 product_execution_admission 更窄，但仍 fail-closed]')
    card = _fully_evidenced_card()
    decision = execution_request_admission(card)
    check(decision.admitted,
          '权重/输入契约/患者级验证/运行资源四项齐备时可以提出执行申请——'
          '即使 code/license/task_compatibility 仍 pending、negative/ood 验证仍未建立')
    check(not product_execution_admission(card).admitted,
          '同一张卡仍通不过更严格的执行批准门槛（能问 != 能批）')

    for field in ('weights', 'input_contract', 'patient_validation', 'cpu_budget'):
        broken = replace(card, **{field: EvidenceState.PENDING})
        decision = execution_request_admission(broken)
        check(not decision.admitted and field in decision.failed_gates,
              f'去掉 {field} 后不能提出执行申请（四项证据逐一 fail-closed）')

    # 申请门槛完全不看 code/license/task_compatibility/negative/ood/自动执行标记，
    # 这四项以外的字段缺失不应影响"能否提出申请"的判定。
    for field, bad in (('code', EvidenceState.NOT_ESTABLISHED), ('license', EvidenceState.UNKNOWN),
                        ('task_compatibility', EvidenceState.PENDING),
                        ('negative_validation', EvidenceState.NOT_ESTABLISHED),
                        ('ood_rejection', EvidenceState.NOT_ESTABLISHED),
                        ('automatic_execution', True), ('product_execution', True)):
        unrelated = replace(card, **{field: bad})
        check(execution_request_admission(unrelated).admitted,
              f'{field} 的取值不影响"能否提出执行申请"这一判定（申请门槛与批准门槛看的是不同证据）')


def test_missing_descriptor_still_blocks_a_request():
    print('[execution_request_admission：基础描述缺失时同样拒绝]')
    card = replace(_fully_evidenced_card(), model_id='')
    decision = execution_request_admission(card)
    check(not decision.admitted and 'model_id' in decision.failed_gates,
          '连模型身份都没记录时，不能提出执行申请（与其他准入函数共用同一套描述符校验）')


def main():
    test_real_candidates_cannot_request_execution_yet()
    test_request_gate_is_narrower_than_grant_gate()
    test_missing_descriptor_still_blocks_a_request()
    total, passed = len(_CHECKS), sum(_CHECKS)
    print(f'\n{passed}/{total} 项通过')
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
