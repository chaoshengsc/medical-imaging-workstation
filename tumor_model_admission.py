"""肿瘤模型证据卡与产品执行准入；纯函数、缺证据即拒绝。"""
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import Enum

import numpy as np


class EvidenceState(str, Enum):
    """A verified state is the only state that can satisfy an admission gate."""

    VERIFIED = 'verified'
    PENDING = 'pending'
    NOT_ESTABLISHED = 'not-established'
    HISTORICAL = 'historical'
    UNKNOWN = 'unknown'


class TypeOutputScope(str, Enum):
    """Closed vocabulary for whether a task emits a per-lesion tumor type."""

    NO_PREDICTION = 'no-prediction'
    PER_LESION_TUMOR_TYPE = 'per-lesion-tumor-type'


class SequenceEvidenceState(str, Enum):
    """Three-state evidence vocabulary used by research-model admission."""

    CONFIRMED = 'confirmed'
    UNKNOWN = 'unknown'
    CONFLICT = 'conflict'


@dataclass(frozen=True)
class MRISequenceEvidence:
    """A recorded sequence conclusion, separate from a model prediction."""

    state: SequenceEvidenceState
    sequence: str
    basis: str
    record_digest: str
    source_binding: object = None


@dataclass(frozen=True)
class SequenceQualificationDecision:
    qualified: bool
    failed_gates: tuple[str, ...]


_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_CONFIRMED_T1 = 'contrast-enhanced-t1-weighted'
_ACCEPTED_SEQUENCE_BASES = frozenset({'human-reviewed-record', 'source-manifest'})


def qualify_contrast_enhanced_t1(evidence, source_binding):
    """Admit ceT1 only from a durable human or source-manifest record."""
    failed = []
    if not isinstance(evidence, MRISequenceEvidence):
        return SequenceQualificationDecision(False, ('sequence_evidence',))
    if evidence.state is not SequenceEvidenceState.CONFIRMED:
        failed.append('state')
    if evidence.sequence != _CONFIRMED_T1:
        failed.append('sequence')
    if evidence.basis not in _ACCEPTED_SEQUENCE_BASES:
        failed.append('basis')
    if not isinstance(evidence.record_digest, str) or not _SHA256_RE.fullmatch(
            evidence.record_digest):
        failed.append('record_digest')
    if evidence.source_binding != source_binding:
        failed.append('source_binding')
    return SequenceQualificationDecision(not failed, tuple(failed))


def dicom_fields_sequence_evidence(source_binding=None, series_description='',
                                   contrast_bolus_agent=''):
    """Record DICOM text as unknown; these fields never auto-confirm T1c."""
    material = f'{series_description}\0{contrast_bolus_agent}'.encode()
    return MRISequenceEvidence(
        state=SequenceEvidenceState.UNKNOWN,
        sequence='unknown', basis='dicom-fields-only',
        record_digest=hashlib.sha256(material).hexdigest(),
        source_binding=source_binding)


@dataclass(frozen=True)
class ModelSourceIdentity:
    """Auditable upstream identity; availability does not authorize execution."""

    upstream_repository: str
    code_commit: str
    code_license: str
    weights_doi: str
    weights_file: str
    weights_file_size: int
    weights_file_md5: str
    weights_sha256: str
    weights_license: str
    upstream_requirements_digest: str
    official_input_filename: str
    official_test_transforms: tuple[str, ...]
    sliding_window: tuple[int, int, int]
    official_device: str


KCL_VS_SEG_T1_MODEL_ID = 'kcl-bmeis-vs-seg-unet2d5-att-hard-t1'
KCL_VS_SEG_T1_TASK_VARIANT = 'vestibular-schwannoma-segmentation-t1'
KCL_VS_SEG_T1_CODE_COMMIT = '33410a2d44e3f57b4df1c3ed005e6d40c0824aa6'
KCL_VS_SEG_T1_WEIGHT_DIGEST = (
    '14b77d2b5f6d2d83bb8ac036e7ab2ef64d2d9c8a03db2c065a2a71fdc63eb123')
KCL_VS_SEG_T1_UPSTREAM_REQUIREMENTS_DIGEST = (
    '7ce0802b6e79cfbfa83b66f9c6a295a8f7d83e37edd70b449477913f96d42c77')
KCL_VS_SEG_T1_UPSTREAM_SPLIT_DIGEST = (
    '366b182e9cd3f842556a8abc8182da3fd7260b2b088f4d8ba0fe4a8dc1974365')
KCL_VS_SEG_T1_PREPROCESS_DIGEST = (
    '37c5e7785dabfdaf9cdcc0c3bab5cc01d80491ee29dfcf91569c56ae97ee4500')
KCL_VS_SEG_T1_POSTPROCESS_DIGEST = (
    'eb98af2cd0f1ea0aa1a5abdadd97c125ba86d9b2e915a67f465587893977467a')

KCL_VS_SEG_T1_SOURCE_IDENTITY = ModelSourceIdentity(
    upstream_repository='https://github.com/KCL-BMEIS/VS_Seg',
    code_commit=KCL_VS_SEG_T1_CODE_COMMIT,
    code_license='Apache-2.0',
    weights_doi='10.5281/zenodo.6323472',
    weights_file='UNet2d5_Att_Hard_T1_final.zip',
    weights_file_size=34377805,
    weights_file_md5='2fb744a616756c08519e79878326f8f8',
    weights_sha256=KCL_VS_SEG_T1_WEIGHT_DIGEST,
    weights_license='CC-BY-4.0',
    upstream_requirements_digest=KCL_VS_SEG_T1_UPSTREAM_REQUIREMENTS_DIGEST,
    official_input_filename='vs_gk_t1_refT1.nii.gz',
    official_test_transforms=(
        'LoadNiftid', 'AddChanneld', 'Orientationd(RAS)',
        'NormalizeIntensityd', 'ToTensord'),
    sliding_window=(384, 384, 64),
    official_device='cuda:0',
)


@dataclass(frozen=True)
class ModelAdmissionCard:
    """Immutable evidence snapshot for one fixed model/task combination."""

    model_id: str
    version: str
    role: str
    task: str
    anatomy: str
    modality: str
    required_sequences: tuple[str, ...]
    output_scope: str
    type_scope: TypeOutputScope
    weights: EvidenceState
    code: EvidenceState
    license: EvidenceState
    input_contract: EvidenceState
    patient_validation: EvidenceState
    negative_validation: EvidenceState
    ood_rejection: EvidenceState
    cpu_budget: EvidenceState
    task_compatibility: EvidenceState
    type_region_binding: EvidenceState
    automatic_execution: bool
    product_execution: bool
    source_identity: ModelSourceIdentity | None = None


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    scope: str
    failed_gates: tuple[str, ...]


_DESCRIPTORS = (
    'model_id', 'version', 'role', 'task', 'anatomy', 'modality',
    'required_sequences', 'output_scope', 'type_scope',
)
_ENGINEERING_EVIDENCE = (
    'weights', 'code', 'license', 'input_contract', 'cpu_budget', 'task_compatibility',
)
_PRODUCT_EVIDENCE = ('patient_validation', 'negative_validation', 'ood_rejection')
_FALSEY_WORDS = {'', 'false', 'missing', 'none', 'not-established', 'unknown'}


def _value(card, field):
    if isinstance(card, ModelAdmissionCard):
        return getattr(card, field)
    if isinstance(card, Mapping):
        return card.get(field)
    return None


def _descriptor_is_known(field, value):
    if field == 'type_scope':
        return isinstance(value, TypeOutputScope)
    if field == 'required_sequences':
        return (isinstance(value, tuple) and len(value) > 0
                and all(isinstance(item, str)
                        and item.strip().lower() not in _FALSEY_WORDS for item in value))
    return isinstance(value, str) and value.strip().lower() not in _FALSEY_WORDS


def engineering_readiness_admission(card):
    """Check only fixed implementation, license, input and resource readiness."""
    failed = [field for field in _DESCRIPTORS
              if not _descriptor_is_known(field, _value(card, field))]
    failed.extend(field for field in _ENGINEERING_EVIDENCE
                  if _value(card, field) is not EvidenceState.VERIFIED)
    return AdmissionDecision(not failed, 'engineering-readiness', tuple(failed))


def product_execution_admission(card):
    """Require engineering readiness plus positive, negative and OOD validation.

    A pass authorizes only the fixed recorded product task.  It does not establish
    clinical generality beyond the card's evidence and scope.
    """
    failed = list(engineering_readiness_admission(card).failed_gates)
    failed.extend(field for field in _PRODUCT_EVIDENCE
                  if _value(card, field) is not EvidenceState.VERIFIED)
    failed.extend(field for field in ('automatic_execution', 'product_execution')
                  if _value(card, field) is not True)
    return AdmissionDecision(not failed, 'product-execution', tuple(failed))


def lesion_type_admission(card):
    """Apply the three hard gates for per-lesion tumor-type output.

    The gates are fixed usable weights, an explicit type-to-region contract,
    and patient-level validation with type plus spatial reference.
    """
    failed = list(product_execution_admission(card).failed_gates)
    type_scope = _value(card, 'type_scope')
    output_scope = _value(card, 'output_scope')
    if (_value(card, 'type_region_binding') is not EvidenceState.VERIFIED
            or type_scope is not TypeOutputScope.PER_LESION_TUMOR_TYPE
            or not isinstance(output_scope, str)
            or not output_scope.strip().lower().replace('_', '-').startswith('per-lesion ')):
        failed.append('type_region_binding')
    return AdmissionDecision(not failed, 'lesion-type', tuple(failed))


BIOMEDPARSE_CARD = ModelAdmissionCard(
    model_id='microsoft-biomedparse-v2',
    version='historical-local-candidate',
    role='historical-research-candidate',
    task='text-conditioned brain MRI candidate segmentation',
    anatomy='brain',
    modality='MRI',
    required_sequences=('task-qualified brain MRI sequence',),
    output_scope='conditional candidate mask',
    type_scope=TypeOutputScope.NO_PREDICTION,
    weights=EvidenceState.HISTORICAL,
    code=EvidenceState.HISTORICAL,
    license=EvidenceState.NOT_ESTABLISHED,
    input_contract=EvidenceState.VERIFIED,
    patient_validation=EvidenceState.NOT_ESTABLISHED,
    negative_validation=EvidenceState.NOT_ESTABLISHED,
    ood_rejection=EvidenceState.NOT_ESTABLISHED,
    cpu_budget=EvidenceState.HISTORICAL,
    task_compatibility=EvidenceState.NOT_ESTABLISHED,
    type_region_binding=EvidenceState.NOT_ESTABLISHED,
    automatic_execution=False,
    product_execution=False,
)


VS_SEG_CARD = ModelAdmissionCard(
    model_id=KCL_VS_SEG_T1_MODEL_ID,
    version=KCL_VS_SEG_T1_CODE_COMMIT,
    role='conditional-research-candidate',
    task='vestibular schwannoma mask segmentation from confirmed contrast-enhanced T1-weighted MRI',
    anatomy='brain/internal auditory canal',
    modality='MRI',
    required_sequences=('confirmed contrast-enhanced T1-weighted MRI',),
    output_scope='conditional candidate mask',
    type_scope=TypeOutputScope.NO_PREDICTION,
    weights=EvidenceState.PENDING,
    code=EvidenceState.VERIFIED,
    license=EvidenceState.VERIFIED,
    input_contract=EvidenceState.PENDING,
    patient_validation=EvidenceState.NOT_ESTABLISHED,
    negative_validation=EvidenceState.NOT_ESTABLISHED,
    ood_rejection=EvidenceState.NOT_ESTABLISHED,
    cpu_budget=EvidenceState.PENDING,
    task_compatibility=EvidenceState.PENDING,
    type_region_binding=EvidenceState.NOT_ESTABLISHED,
    automatic_execution=False,
    product_execution=False,
    source_identity=KCL_VS_SEG_T1_SOURCE_IDENTITY,
)


# The fixed KCL T1 identity below is intentionally independent from the
# BiomedParse result/cache schema.  These gates load no model and run no Qt.
@dataclass(frozen=True)
class SourceBinding:
    study_instance_uid: str
    series_instance_uid: str
    source_digest: str
    geometry_digest: str
    ordered_sop_digest: str


@dataclass(frozen=True)
class ModelSpaceContract:
    input_filename: str
    transforms: tuple[str, ...]
    model_axis_codes: str
    sliding_window: tuple[int, int, int]


OFFICIAL_VS_T1_MODEL_SPACE = ModelSpaceContract(
    input_filename='vs_gk_t1_refT1.nii.gz',
    transforms=('LoadNiftid', 'AddChanneld', 'Orientationd(RAS)',
                'NormalizeIntensityd', 'ToTensord'),
    model_axis_codes='RAS',
    sliding_window=(384, 384, 64),
)


@dataclass(frozen=True)
class VST1Request:
    task_variant: str
    model_id: str
    source_binding: SourceBinding
    sequence_evidence: object
    model_space: ModelSpaceContract


@dataclass(frozen=True)
class VSQualificationDecision:
    qualified: bool
    scope: str
    failed_gates: tuple[str, ...]
    source_binding: SourceBinding | None = None


def _binding_complete(binding):
    return (isinstance(binding, SourceBinding)
            and isinstance(binding.study_instance_uid, str)
            and bool(binding.study_instance_uid.strip())
            and isinstance(binding.series_instance_uid, str)
            and bool(binding.series_instance_uid.strip())
            and all(isinstance(value, str) and _SHA256_RE.fullmatch(value)
                    for value in (binding.source_digest,
                                  binding.geometry_digest,
                                  binding.ordered_sop_digest)))


def _canonical_digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def qualify_vs_t1_source(series):
    """Rebuild a real ``SeriesVolume`` and derive its immutable VS source key."""
    # Local import keeps the admission module independent of the DICOM loader at
    # import time while still requiring the loader's concrete product type here.
    from study_data import SeriesVolume

    failed = []
    if not isinstance(series, SeriesVolume):
        return VSQualificationDecision(
            False, 'vs-t1-source-qualification', ('series_volume',))
    try:
        rebuilt = SeriesVolume.from_datasets(series.datasets)
    except (AttributeError, TypeError, ValueError):
        return VSQualificationDecision(
            False, 'vs-t1-source-qualification', ('series_rebuild',))
    if series.modality != 'MR' or rebuilt.modality != 'MR':
        failed.append('modality')
    if (rebuilt.affine is None or rebuilt.geometry_binding is None
            or series.affine is None or series.geometry_binding is None):
        failed.append('geometry')
    if (rebuilt.source_binding is None
            or rebuilt.source_binding.get('digest') is None):
        failed.append('source_binding')
    if (not np.array_equal(series.volume, rebuilt.volume)
            or series.source_binding != rebuilt.source_binding
            or not np.array_equal(series.affine, rebuilt.affine)
            or series.geometry_binding != rebuilt.geometry_binding):
        failed.append('series_rebuild')
    if failed:
        return VSQualificationDecision(
            False, 'vs-t1-source-qualification', tuple(dict.fromkeys(failed)))
    ordered_sops = [str(ds.SOPInstanceUID) for ds in rebuilt.datasets]
    binding = SourceBinding(
        study_instance_uid=rebuilt.study_uid,
        series_instance_uid=rebuilt.series_uid,
        source_digest=rebuilt.source_binding['digest'],
        geometry_digest=_canonical_digest(rebuilt.geometry_binding),
        ordered_sop_digest=_canonical_digest(ordered_sops),
    )
    return VSQualificationDecision(
        True, 'vs-t1-source-qualification', (), binding)


def qualify_vs_t1_request(request, series):
    """Qualify static request/source evidence without authorizing execution."""
    failed = []
    if not isinstance(request, VST1Request):
        return VSQualificationDecision(False, 'vs-t1-request-qualification', ('request',))
    source_decision = qualify_vs_t1_source(series)
    binding = source_decision.source_binding
    failed.extend(source_decision.failed_gates)
    if request.task_variant != KCL_VS_SEG_T1_TASK_VARIANT:
        failed.append('task_variant')
    if request.model_id != KCL_VS_SEG_T1_MODEL_ID:
        failed.append('model_id')
    if (not _binding_complete(binding)
            or not _binding_complete(request.source_binding)
            or request.source_binding != binding):
        failed.append('source_binding')
    if not qualify_contrast_enhanced_t1(
            request.sequence_evidence, binding).qualified:
        failed.append('sequence_evidence')
    if request.model_space != OFFICIAL_VS_T1_MODEL_SPACE:
        failed.append('model_space')
    return VSQualificationDecision(
        not failed, 'vs-t1-request-qualification', tuple(dict.fromkeys(failed)), binding)


def admit_vs_t1_execution(request, series):
    """Execution remains closed until a CPU adapter/runtime is verified."""
    qualification = qualify_vs_t1_request(request, series)
    failed = [*qualification.failed_gates, 'engineering_runtime_not_ready']
    return AdmissionDecision(False, 'vs-t1-execution', tuple(dict.fromkeys(failed)))


def vs_request_digest(request):
    """Digest the complete fixed request, including sequence/source evidence."""
    if not isinstance(request, VST1Request):
        return None
    evidence = request.sequence_evidence
    if not isinstance(evidence, MRISequenceEvidence):
        return None
    return _canonical_digest({
        'task_variant': request.task_variant,
        'model_id': request.model_id,
        'source_binding': asdict(request.source_binding),
        'sequence_evidence': {
            'state': evidence.state.value if isinstance(
                evidence.state, SequenceEvidenceState) else evidence.state,
            'sequence': evidence.sequence,
            'basis': evidence.basis,
            'record_digest': evidence.record_digest,
            'source_binding': asdict(evidence.source_binding)
            if isinstance(evidence.source_binding, SourceBinding) else None,
        },
        'model_space': asdict(request.model_space),
    })


@dataclass(frozen=True)
class SpatialTrace:
    source_axis_codes: str
    source_array_axes: str
    model_axis_codes: str
    model_array_axes: str
    output_axis_codes: str
    output_array_axes: str
    source_shape: tuple[int, int, int]
    model_shape: tuple[int, int, int]
    output_shape: tuple[int, int, int]
    source_to_model_affine_digest: str
    model_to_source_affine_digest: str
    left_right_preserved: bool


@dataclass(frozen=True)
class VSResultIdentity:
    model_id: str
    code_commit: str
    weight_digest: str
    upstream_requirements_digest: str
    task_variant: str
    preprocess_digest: str
    postprocess_digest: str
    request_digest: str
    source_binding: SourceBinding
    mask_digest: str
    mask_shape: tuple[int, int, int]
    mask_dtype: str
    spatial_trace: SpatialTrace
    output_kind: str
    type_status: str
    type_scope: str
    type_prediction: object


@dataclass(frozen=True)
class ResultDecision:
    accepted: bool
    failed_gates: tuple[str, ...]


def _result_value(record, field):
    if isinstance(record, Mapping):
        return record.get(field)
    return getattr(record, field, None)


def _has_result_field(record, field):
    if isinstance(record, Mapping):
        return field in record
    return hasattr(record, field)


def _valid_shape(value):
    return (isinstance(value, tuple) and len(value) == 3
            and all(isinstance(item, int) and not isinstance(item, bool) and item > 0
                    for item in value))


def _valid_spatial_trace(trace, source_shape=None):
    return (isinstance(trace, SpatialTrace)
            and trace.source_axis_codes == 'LPS'
            and trace.source_array_axes == 'zyx'
            and trace.model_axis_codes == 'RAS'
            and trace.model_array_axes == 'xyz'
            and trace.output_axis_codes == 'LPS'
            and trace.output_array_axes == 'zyx'
            and _valid_shape(trace.source_shape)
            and _valid_shape(trace.model_shape)
            and _valid_shape(trace.output_shape)
            and trace.output_shape == trace.source_shape
            and (source_shape is None or trace.source_shape == tuple(source_shape))
            and bool(_SHA256_RE.fullmatch(trace.source_to_model_affine_digest))
            and bool(_SHA256_RE.fullmatch(trace.model_to_source_affine_digest))
            and trace.left_right_preserved is True)


_RESULT_IDENTITY = {
    'model_id': KCL_VS_SEG_T1_MODEL_ID,
    'code_commit': KCL_VS_SEG_T1_CODE_COMMIT,
    'weight_digest': KCL_VS_SEG_T1_WEIGHT_DIGEST,
    'upstream_requirements_digest': KCL_VS_SEG_T1_UPSTREAM_REQUIREMENTS_DIGEST,
    'task_variant': KCL_VS_SEG_T1_TASK_VARIANT,
    'preprocess_digest': KCL_VS_SEG_T1_PREPROCESS_DIGEST,
    'postprocess_digest': KCL_VS_SEG_T1_POSTPROCESS_DIGEST,
}


def _actual_mask_digest(mask):
    return hashlib.sha256(np.ascontiguousarray(mask).tobytes()).hexdigest()


def validate_vs_result(result, request, series, mask):
    """Recompute source/request/mask identity; keep runtime adapter gate closed."""
    failed = []
    for field in VSResultIdentity.__dataclass_fields__:
        if not _has_result_field(result, field):
            failed.append(field)
    qualification = qualify_vs_t1_request(request, series)
    if not qualification.qualified:
        failed.extend(qualification.failed_gates)
    for field, expected in _RESULT_IDENTITY.items():
        if _result_value(result, field) != expected:
            failed.append(field)
    source_binding = _result_value(result, 'source_binding')
    if (not _binding_complete(source_binding)
            or source_binding != qualification.source_binding):
        failed.append('source_binding')
    expected_request_digest = vs_request_digest(request)
    if (expected_request_digest is None
            or _result_value(result, 'request_digest') != expected_request_digest):
        failed.append('request_digest')
    source_shape = getattr(getattr(series, 'volume', None), 'shape', None)
    if not _valid_spatial_trace(_result_value(result, 'spatial_trace'), source_shape):
        failed.append('spatial_trace')
    if not isinstance(mask, np.ndarray):
        failed.append('mask')
    else:
        if source_shape is None or mask.shape != tuple(source_shape):
            failed.append('mask_shape')
        if mask.dtype != np.uint8 or _result_value(result, 'mask_dtype') != 'uint8':
            failed.append('mask_dtype')
        if not np.all((mask == 0) | (mask == 1)):
            failed.append('mask_binary')
        if tuple(_result_value(result, 'mask_shape') or ()) != mask.shape:
            failed.append('mask_shape')
        if _result_value(result, 'mask_digest') != _actual_mask_digest(mask):
            failed.append('mask_digest')
    if _result_value(result, 'output_kind') != 'binary-mask':
        failed.append('output_kind')
    if (_result_value(result, 'type_status') != 'unknown'
            or _result_value(result, 'type_scope') != 'no-prediction'
            or _result_value(result, 'type_prediction') is not None):
        failed.append('type_status')
    # Static fields and actual source/mask checks cannot prove the unimplemented
    # source→RAS→source adapter or its left/right roundtrip.
    failed.append('runtime_adapter_not_verified')
    return ResultDecision(not failed, tuple(dict.fromkeys(failed)))


@dataclass(frozen=True)
class VSEvaluationEvidence:
    case_ids: tuple[str, ...]
    evidence_role: str
    upstream_split_digest: str


_KNOWN_TRAINING_CASES = frozenset({
    'VS-SEG-001', 'VS-SEG-002', 'VS-SEG-003',
    'VS_GK_1', 'VS_GK_2', 'VS_GK_3',
})


def validate_vs_evaluation_evidence(evidence):
    """Keep official training-overlap cases out of independent-performance claims."""
    if not isinstance(evidence, VSEvaluationEvidence):
        return ResultDecision(False, ('evaluation_evidence',))
    failed = []
    if (not isinstance(evidence.case_ids, tuple) or not evidence.case_ids
            or not all(isinstance(case, str) and case.strip()
                       for case in evidence.case_ids)):
        failed.append('case_ids')
    normalized = {case.strip().upper().replace('_', '-')
                  for case in evidence.case_ids if isinstance(case, str)}
    training_overlap = bool(normalized & {
        case.replace('_', '-') for case in _KNOWN_TRAINING_CASES})
    if evidence.evidence_role == 'training-overlap-quarantine':
        if (not training_overlap
                or len(normalized) != len(normalized & {
                    case.replace('_', '-') for case in _KNOWN_TRAINING_CASES})):
            failed.append('training_overlap')
        if evidence.upstream_split_digest != KCL_VS_SEG_T1_UPSTREAM_SPLIT_DIGEST:
            failed.append('upstream_split_digest')
    elif evidence.evidence_role == 'independent-performance':
        if training_overlap:
            failed.append('training_overlap')
        failed.append('independent_cohort_not_established')
    else:
        failed.append('evidence_role')
    return ResultDecision(not failed, tuple(dict.fromkeys(failed)))
