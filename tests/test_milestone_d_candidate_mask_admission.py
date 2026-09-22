#!/usr/bin/env python
# =============================================================================
# 里程碑 D 验收（第 2 条）：候选模型接入为"需复核的候选 mask"，默认不自动采用、
# 不宣称瘤种。
#
# 本仓库当前没有任何候选模型的真实权重/可运行代码（BIOMEDPARSE_CARD、VS_SEG_CARD
# 均处于研究记录状态，见 tumor_model_admission.py），因此本轮只交付：
#   1. 新的准入闸门 candidate_mask_admission / candidate_mask_provenance
#      （tumor_model_admission.py，纯函数，不运行任何模型）
#   2. 用真实 VS-SEG-002/003 数据 + 一个"假设已通过准入"的合成证据卡，验证接入
#      契约本身（只读候选版本、默认不采用、不带瘤种字段）成立
#   3. 确认仓库里两个真实候选（BIOMEDPARSE_CARD、VS_SEG_CARD）在这个新闸门下
#      仍被拒绝——不是只测虚构的通过用例
#
# 不写依赖不存在权重文件的"占位成功"：这里的合成证据卡只用来验证数据模型/接入
# 契约本身，不代表任何真实模型已被验证或获准执行。
#
# 数据来自 Annotation_Projects/recovered_vestibular_schwannoma_cases/（不入库，
# 见 .gitignore），本机不存在时跳过数据相关部分并给出明确原因，不伪造通过。
#
# 运行：conda activate dicom_gui && python tests/test_milestone_d_candidate_mask_admission.py
# =============================================================================
import json
import os
import sys
from dataclasses import replace

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import numpy as np

from study_data import StudyDocument, read_series_directory
from tumor_model_admission import (
    BIOMEDPARSE_CARD,
    VS_SEG_CARD,
    EvidenceState,
    TypeOutputScope,
    candidate_mask_admission,
    candidate_mask_provenance,
)

_CASES_DIR = os.path.join(_ROOT, 'Annotation_Projects', 'recovered_vestibular_schwannoma_cases')
_MANIFEST = os.path.join(_CASES_DIR, 'manifest.json')

_CHECKS = []


def check(cond, label):
    _CHECKS.append(bool(cond))
    print(('  PASS ' if cond else '  FAIL ') + label)
    if not cond:
        raise AssertionError(label)


def _fully_evidenced_candidate_card():
    """一张合成的、假设通过候选准入的证据卡；不对应任何真实可运行模型或权重。"""
    from tumor_model_admission import ModelAdmissionCard
    return ModelAdmissionCard(
        model_id='synthetic-candidate-model', version='1.0-test-only', role='candidate-for-review',
        task='synthetic lesion candidate segmentation', anatomy='brain', modality='MRI',
        required_sequences=('T1',), output_scope='conditional candidate mask',
        type_scope=TypeOutputScope.NO_PREDICTION,
        weights=EvidenceState.VERIFIED, code=EvidenceState.VERIFIED, license=EvidenceState.VERIFIED,
        input_contract=EvidenceState.VERIFIED, task_compatibility=EvidenceState.VERIFIED,
        patient_validation=EvidenceState.NOT_ESTABLISHED, negative_validation=EvidenceState.NOT_ESTABLISHED,
        ood_rejection=EvidenceState.NOT_ESTABLISHED, cpu_budget=EvidenceState.NOT_ESTABLISHED,
        type_region_binding=EvidenceState.NOT_ESTABLISHED,
        automatic_execution=False, product_execution=False,
    )


def test_real_current_candidates_are_rejected():
    print('[candidate_mask_admission：仓库里两个真实候选仍被拒绝]')
    for card in (BIOMEDPARSE_CARD, VS_SEG_CARD):
        decision = candidate_mask_admission(card)
        check(not decision.admitted,
              f'{card.model_id} 在候选 mask 准入下仍被拒绝（无真实可用权重/许可）')
        try:
            candidate_mask_provenance(card)
            raised = False
        except ValueError:
            raised = True
        check(raised, f'{card.model_id} 无法产出候选 provenance（准入未通过时拒绝生成）')


def test_candidate_gate_does_not_require_product_execution_evidence():
    print('[candidate_mask_admission：候选复核门槛低于自动执行/产品执行，但仍是 fail-closed]')
    card = _fully_evidenced_candidate_card()
    decision = candidate_mask_admission(card)
    check(decision.admitted,
          '合成的完整候选证据卡（不含 patient/negative/OOD 验证、不自动执行）仍能通过候选复核门槛')
    for field, bad in (('weights', EvidenceState.PENDING), ('code', EvidenceState.UNKNOWN),
                        ('license', EvidenceState.NOT_ESTABLISHED),
                        ('input_contract', EvidenceState.PENDING),
                        ('task_compatibility', EvidenceState.UNKNOWN)):
        broken = replace(card, **{field: bad})
        decision = candidate_mask_admission(broken)
        check(not decision.admitted and field in decision.failed_gates,
              f'候选复核门槛仍对 {field} 缺证据 fail-closed（不因门槛较低而放行）')

    # 用户明确要求收紧：HISTORICAL（曾在旧代码/旧权重上验证过，未重新核实）不再算数，
    # 候选复核这一层现在只认 VERIFIED——不因门槛低于产品执行就放宽到"曾经验证过"。
    for field in ('weights', 'code', 'license', 'input_contract', 'task_compatibility'):
        historical = replace(card, **{field: EvidenceState.HISTORICAL})
        decision = candidate_mask_admission(historical)
        check(not decision.admitted and field in decision.failed_gates,
              f'{field} 只是 HISTORICAL（未重新核实）时仍拒绝，候选复核只接受 VERIFIED')


def test_candidate_provenance_never_claims_a_tumor_type():
    print('[candidate_mask_provenance：不宣称瘤种]')
    card = _fully_evidenced_candidate_card()
    provenance = candidate_mask_provenance(card)
    check('type' not in provenance and 'tumor_type' not in provenance,
          '候选 provenance 不包含任何瘤种字段')
    check(provenance['requires_review'] is True and provenance['auto_adopted'] is False,
          '候选 provenance 显式标注需复核、未采用')
    check(provenance['origin'] == 'candidate-model'
          and provenance['model_id'] == card.model_id and provenance['model_version'] == card.version,
          '候选 provenance 绑定生成它的模型身份和版本')

    type_card = replace(card, type_scope=TypeOutputScope.PER_LESION_TUMOR_TYPE,
                        output_scope='per-lesion tumor-type prediction',
                        type_region_binding=EvidenceState.VERIFIED)
    from tumor_model_admission import lesion_type_admission
    check(not lesion_type_admission(type_card).admitted,
          '即使证据卡的 type_scope 声称按病灶预测瘤种，更严格的 lesion_type_admission '
          '仍因缺 patient/negative/OOD 验证而拒绝——候选复核这一层本身从不检查/授权瘤种声明')
    check('type' not in candidate_mask_provenance(type_card),
          '候选 provenance 生成路径本身就不读取 type_scope，不会因证据卡声称瘤种而带出瘤种字段')


def _run_real_data_case(case):
    print(f'=== {case["patient_id"]} ===')
    dicom_dir = os.path.join(_CASES_DIR, case['dicom_path'])
    source = read_series_directory(dicom_dir).series[0]
    doc = StudyDocument(source.study_uid)
    doc.attach_sources([source])
    sid = source.series_uid
    # 病灶候选天然对应 working-manual（kind='lesion'）而非默认的 working-organs；
    # 与里程碑 A/B/C 对 MR 病灶标注使用的图层保持一致。
    doc.series[sid].active_layer_id = 'working-manual'
    shape = doc.series[sid].working_mask.shape

    before_active_layer = doc.series[sid].active_layer_id
    before_working_mask = doc.series[sid].working_mask.copy()

    card = _fully_evidenced_candidate_card()
    provenance = candidate_mask_provenance(card)
    candidate_mask = np.zeros(shape, dtype=np.uint8)
    z0 = shape[0] // 2
    candidate_mask[z0 - 3:z0 + 3, 50:70, 50:70] = 1

    version = doc.add_ai_result(sid, candidate_mask, None, provenance, kind='lesion')
    layer = doc.series[sid].layers[version]

    check(layer.readonly, f'{case["patient_id"]} 候选 mask 作为只读版本接入，不能被直接改写')
    check(layer.provenance == provenance,
          f'{case["patient_id"]} 接入后的图层 provenance 与候选契约生成的完全一致')
    check(doc.series[sid].active_layer_id == before_active_layer,
          f'{case["patient_id"]} 接入候选 mask 后当前活动图层未变（默认不自动采用）')
    check(np.array_equal(doc.series[sid].working_mask, before_working_mask),
          f'{case["patient_id"]} 接入候选 mask 后工作结果未被改动（不是隐式采用）')
    check(np.array_equal(layer.mask, candidate_mask),
          f'{case["patient_id"]} 只读候选版本本身保留了完整的候选内容，供后续人工复核对照')

    doc.adopt_ai_result(sid, version, layer_id='working-manual')
    check(np.array_equal(doc.series[sid].working_mask, candidate_mask),
          f'{case["patient_id"]} 采用候选版本是一次独立、显式的操作，接入本身不会代为完成')
    doc.undo()
    check(np.array_equal(doc.series[sid].working_mask, before_working_mask),
          f'{case["patient_id"]} 撤销采用后恢复到接入候选前的工作结果，只读候选版本仍完整保留')
    check(np.array_equal(doc.series[sid].layers[version].mask, candidate_mask),
          f'{case["patient_id"]} 撤销采用不影响候选版本本身')
    print(f'{case["patient_id"]} PASS')


def test_real_data_ingestion_contract():
    if not os.path.isfile(_MANIFEST):
        print(f'WARN: 未找到 {_MANIFEST}，跳过候选 mask 接入契约的真实数据部分（本机未恢复该数据）')
        return
    with open(_MANIFEST, encoding='utf-8') as fh:
        manifest = json.load(fh)
    for case in manifest['cases']:
        _run_real_data_case(case)


def main():
    test_real_current_candidates_are_rejected()
    test_candidate_gate_does_not_require_product_execution_evidence()
    test_candidate_provenance_never_claims_a_tumor_type()
    test_real_data_ingestion_contract()
    total, passed = len(_CHECKS), sum(_CHECKS)
    print(f'\n{passed}/{total} 项通过')
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
