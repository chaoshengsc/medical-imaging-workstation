"""Qt-free tumor-model admission gates."""
import unittest
from dataclasses import FrozenInstanceError, replace

from tumor_model_admission import (
    BIOMEDPARSE_CARD,
    VS_SEG_CARD,
    EvidenceState,
    ModelAdmissionCard,
    TypeOutputScope,
    engineering_readiness_admission,
    lesion_type_admission,
    product_execution_admission,
)


def complete_card():
    return ModelAdmissionCard(
        model_id='fixed-model', version='1.0', role='product-task',
        task='fixed lesion segmentation and type prediction', anatomy='brain',
        modality='MRI', required_sequences=('T1c',), output_scope='per-lesion mask',
        type_scope=TypeOutputScope.PER_LESION_TUMOR_TYPE,
        weights=EvidenceState.VERIFIED,
        code=EvidenceState.VERIFIED, license=EvidenceState.VERIFIED,
        input_contract=EvidenceState.VERIFIED,
        patient_validation=EvidenceState.VERIFIED,
        negative_validation=EvidenceState.VERIFIED,
        ood_rejection=EvidenceState.VERIFIED,
        cpu_budget=EvidenceState.VERIFIED,
        task_compatibility=EvidenceState.VERIFIED,
        type_region_binding=EvidenceState.VERIFIED,
        automatic_execution=True, product_execution=True,
    )


class TumorModelAdmissionTests(unittest.TestCase):
    def test_missing_unknown_and_false_fail_closed(self):
        for candidate in (
                None,
                {},
                {**complete_card().__dict__, 'license': EvidenceState.UNKNOWN},
                {**complete_card().__dict__, 'product_execution': False}):
            with self.subTest(candidate=candidate):
                self.assertFalse(product_execution_admission(candidate).admitted)

        string_scope = product_execution_admission({
            **complete_card().__dict__, 'type_scope': 'per-lesion-tumor-type',
        })
        self.assertFalse(string_scope.admitted)
        self.assertIn('type_scope', string_scope.failed_gates)

    def test_only_complete_engineering_card_is_admitted(self):
        card = complete_card()
        self.assertTrue(engineering_readiness_admission(card).admitted)
        self.assertTrue(engineering_readiness_admission(
            replace(card, type_scope=TypeOutputScope.NO_PREDICTION)).admitted)
        for field in ('weights', 'code', 'license', 'input_contract', 'cpu_budget',
                      'task_compatibility'):
            with self.subTest(field=field):
                decision = engineering_readiness_admission(
                    replace(card, **{field: EvidenceState.PENDING}))
                self.assertFalse(decision.admitted)
                self.assertIn(field, decision.failed_gates)

    def test_product_execution_combines_readiness_validation_and_flags(self):
        self.assertTrue(product_execution_admission(complete_card()).admitted)
        mutations = (
            ('license', {'license': EvidenceState.PENDING}),
            ('patient_validation', {'patient_validation': EvidenceState.NOT_ESTABLISHED}),
            ('negative_validation', {'negative_validation': EvidenceState.UNKNOWN}),
            ('ood_rejection', {'ood_rejection': EvidenceState.PENDING}),
            ('automatic_execution', {'automatic_execution': False}),
            ('product_execution', {'product_execution': False}),
        )
        for gate, mutation in mutations:
            with self.subTest(gate=gate):
                decision = product_execution_admission(replace(complete_card(), **mutation))
                self.assertFalse(decision.admitted)
                self.assertIn(gate, decision.failed_gates)

    def test_lesion_type_combines_product_gate_and_explicit_per_lesion_scope(self):
        card = complete_card()
        self.assertTrue(lesion_type_admission(card).admitted)
        mutations = (
            ('weights', {'weights': EvidenceState.PENDING}),
            ('ood_rejection', {'ood_rejection': EvidenceState.PENDING}),
            ('type_region_binding', {'type_region_binding': EvidenceState.UNKNOWN}),
            ('type_region_binding', {'output_scope': 'study-level scores'}),
            ('type_region_binding', {'type_scope': TypeOutputScope.NO_PREDICTION}),
            ('type_region_binding', {'type_scope': 'per-lesion no-type-prediction'}),
            ('type_region_binding', {'type_scope': 'per-lesion type not supported'}),
            ('type_region_binding', {'type_scope': 'per-lesion pseudotype placeholder'}),
            ('type_region_binding', {'type_scope': 'study-level tumor-type prediction'}),
            ('type_region_binding', {'type_scope': 'whole-image tumor-type prediction'}),
        )
        for gate, mutation in mutations:
            with self.subTest(gate=gate, mutation=mutation):
                decision = lesion_type_admission(replace(card, **mutation))
                self.assertFalse(decision.admitted)
                self.assertIn(gate, decision.failed_gates)

    def test_current_candidates_are_research_only(self):
        for card in (BIOMEDPARSE_CARD, VS_SEG_CARD):
            with self.subTest(model=card.model_id):
                self.assertFalse(product_execution_admission(card).admitted)
                self.assertFalse(lesion_type_admission(card).admitted)
                self.assertFalse(card.automatic_execution)
                self.assertFalse(card.product_execution)
        self.assertIs(VS_SEG_CARD.weights, EvidenceState.VERIFIED)
        denied = product_execution_admission(VS_SEG_CARD)
        self.assertIn('input_contract', denied.failed_gates)
        self.assertIn('cpu_budget', denied.failed_gates)
        self.assertIn('task_compatibility', denied.failed_gates)
        self.assertEqual(BIOMEDPARSE_CARD.task_compatibility,
                         EvidenceState.NOT_ESTABLISHED)

    def test_cards_are_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            BIOMEDPARSE_CARD.role = 'product'


if __name__ == '__main__':
    unittest.main()
