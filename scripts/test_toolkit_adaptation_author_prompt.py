# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free prompt contract tests for the LLM adaptation author."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.toolkit_adaptation_dossier import (
    ADAPTATION_DOSSIER_STATUS_READY,
    ADAPTATION_DOSSIER_STATUS_REFUSED,
    ADAPTATION_DOSSIER_VERSION,
    ADAPTATION_MODE_LLM,
    ADAPTATION_NOTICE,
    REQUIRED_ADAPTATION_DOSSIER_FIELDS,
    VALID_ADAPTATION_DOSSIER_STATUSES,
    VALID_RIGHTS_CLASSES,
    VALID_SOURCE_PROFILES,
    parse_adaptation_dossier,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = REPO_ROOT / "prompts" / "toolkit" / "adaptation_author_prompt.txt"
VALID_FIXTURE_PATH = (
    REPO_ROOT / "scripts" / "fixtures" / "toolkit_adaptation_dossier_valid.json"
)


def _prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _prompt_normalized() -> str:
    """Collapse whitespace so multi-word phrase assertions are wrap-safe."""
    import re

    return re.sub(r"\s+", " ", _prompt_text())


def _load_fixture():
    with VALID_FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _extract_fenced_json_blocks(text: str):
    """Return the raw JSON payloads between ```json and ``` fences."""
    blocks = []
    in_block = False
    buffer = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "```json":
            in_block = True
            buffer = []
            continue
        if stripped == "```":
            if in_block:
                blocks.append("\n".join(buffer))
                in_block = False
            continue
        if in_block:
            buffer.append(line)
    return blocks


class TestAdaptationAuthorPromptFile(unittest.TestCase):
    """The adaptation author prompt exists and states the author contract."""

    def test_prompt_file_exists_and_is_non_empty(self):
        self.assertTrue(PROMPT_PATH.is_file(), "adaptation author prompt missing")
        text = _prompt_text()
        self.assertGreater(len(text), 2000)

    def test_prompt_is_ascii_only(self):
        text = _prompt_text()
        non_ascii = [ch for ch in text if ord(ch) >= 128]
        self.assertEqual(non_ascii, [], "non-ASCII characters in the prompt")

    def test_requires_strict_json_only_output(self):
        text = _prompt_normalized()
        self.assertIn("VALID JSON ONLY", text)
        self.assertIn("json.loads()", text)
        self.assertIn("No markdown, no code fences, no prose", text)
        self.assertIn("single JSON object", text)
        self.assertIn("Reply with raw JSON only", text)

    def test_defines_all_source_profiles_and_selection_guidance(self):
        text = _prompt_normalized()
        for profile in VALID_SOURCE_PROFILES:
            self.assertIn(f'"{profile}"', text, f"missing profile {profile}")
        self.assertIn("SOURCE PROFILE SELECTION", text)
        self.assertIn("dominant shape of the source", text)
        self.assertIn("Never invent a profile", text)

    def test_keeps_omission_inference_and_fidelity_categories_separate(self):
        text = _prompt_normalized()
        self.assertIn("retained_source_elements", text)
        self.assertIn("omitted_source_elements", text)
        self.assertIn("original_adaptation_elements", text)
        self.assertIn("Bounded inferences are allowed", text)
        self.assertIn("Do NOT fabricate source provenance", text)
        self.assertIn("Do NOT claim literal fidelity", text)
        self.assertIn("record the ambiguity in assumptions or warnings", text)

    def test_requires_original_connective_material(self):
        text = _prompt_normalized()
        self.assertIn("ORIGINAL CONTENT REQUIREMENT", text)
        self.assertIn("original NEQ-TTRPG connective material", text)
        self.assertIn("Do NOT copy source prose verbatim at length", text)
        self.assertIn("bounded and attributable", text)

    def test_enforces_neq_and_srd_521_constraints(self):
        text = _prompt_normalized()
        self.assertIn("SRD 5.2.1", text)
        self.assertIn('"5th edition" or "5e"', text)
        self.assertIn("generic fantasy", text)
        self.assertIn("unsupported proprietary settings", text)
        self.assertIn("Python applies SRD attribution", text)

    def test_forbids_fences_credentials_prompts_and_unbounded_excerpts(self):
        text = _prompt_normalized()
        self.assertIn("no code fences", text)
        self.assertIn("credentials, API keys, tokens", text)
        self.assertIn("raw prompts", text)
        self.assertIn("unbounded source excerpts", text)

    def test_requires_ascii_output_and_bounded_fields(self):
        text = _prompt_normalized()
        self.assertIn("Output ASCII characters only", text)
        self.assertIn("No smart quotes, no em-dashes", text)
        self.assertIn("bounded lengths", text)

    def test_python_remains_the_authority(self):
        text = _prompt_normalized()
        self.assertIn("Python owns schema, mechanics, topology, validation", text)
        self.assertIn("artifact safety, and publication", text)
        self.assertIn("You propose narrative content only", text)
        self.assertIn("Do NOT emit instructions for Python to execute", text)

    def test_documents_status_rights_and_provenance_fields(self):
        text = _prompt_normalized()
        for status in VALID_ADAPTATION_DOSSIER_STATUSES:
            self.assertIn(f'"{status}"', text, f"missing status {status}")
        for rights in VALID_RIGHTS_CLASSES:
            self.assertIn(f'"{rights}"', text, f"missing rights class {rights}")
        self.assertIn('"toolkit_adaptation_dossier.v1"', text)
        self.assertIn('"llm_adaptation"', text)
        self.assertIn(ADAPTATION_NOTICE, text)
        self.assertIn("rights_review_required", text)
        self.assertIn("rights_review_status", text)
        self.assertIn("Echo the provided source hash exactly", text)

    def test_documents_every_required_dossier_field_by_name(self):
        text = _prompt_normalized()
        missing = [
            field for field in REQUIRED_ADAPTATION_DOSSIER_FIELDS
            if field not in text
        ]
        self.assertEqual(missing, [], f"undocumented required fields: {missing}")


class TestAdaptationAuthorPromptDossierCompatibility(unittest.TestCase):
    """The documented output shape satisfies the v1 dossier parser contract."""

    def setUp(self):
        self.blocks = _extract_fenced_json_blocks(_prompt_text())

    def test_prompt_contains_exactly_two_fenced_examples(self):
        self.assertEqual(len(self.blocks), 2)

    def test_valid_example_parses_as_ready_and_build_ready(self):
        result = parse_adaptation_dossier(self.blocks[0])
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual(result["dossier_status"], ADAPTATION_DOSSIER_STATUS_READY)
        self.assertTrue(result["build_ready"])
        self.assertEqual(result["diagnostics"], [])

    def test_refused_example_parses_as_refused_and_not_build_ready(self):
        result = parse_adaptation_dossier(self.blocks[1])
        self.assertTrue(result["valid"], result["diagnostics"])
        self.assertEqual(result["dossier_status"], ADAPTATION_DOSSIER_STATUS_REFUSED)
        self.assertFalse(result["build_ready"])

    def test_examples_alignment_with_dossier_constants(self):
        text = _prompt_text()
        self.assertIn(ADAPTATION_DOSSIER_VERSION, text)
        self.assertIn(ADAPTATION_MODE_LLM, text)
        self.assertIn(ADAPTATION_NOTICE, text)
        for profile in VALID_SOURCE_PROFILES:
            self.assertIn(f'"{profile}"', text)

    def test_fixture_shape_matches_the_documented_example_shape(self):
        fixture = _load_fixture()
        example = json.loads(self.blocks[0])
        self.assertEqual(
            sorted(fixture.keys()),
            sorted(example.keys()),
            "fixture and documented example shapes diverged",
        )
        result = parse_adaptation_dossier(fixture)
        self.assertTrue(result["valid"])
        self.assertTrue(result["build_ready"])


class TestAdaptationAuthorPromptRightsBasisContract(unittest.TestCase):
    """The author prompt treats rights_basis as a Python-owned opaque token.

    The provider MUST echo the canonical value character-for-character and
    MUST NOT paraphrase it into explanatory prose. The documented examples
    must use canonical tokens, never prose.
    """

    LEGACY_PROSE_RIGHTS_BASIS_VALUES = (
        "Operator attested that the uploaded source is user-authored.",
        "No rights classification was provided for the uploaded source.",
    )

    CANONICAL_UPLOAD_RIGHTS_BASIS = "user_authored_uploaded_adventure"
    CANONICAL_RESTRICTED_RIGHTS_BASIS = "third_party_copyright_restricted_upload"

    def setUp(self):
        self.text = _prompt_text()
        self.normalized = _prompt_normalized()
        self.blocks = _extract_fenced_json_blocks(self.text)

    def test_requires_exact_character_for_character_echo_instruction(self):
        text = self.normalized
        self.assertIn("rights_basis", text)
        self.assertIn("Python-owned opaque value", text)
        self.assertIn("MUST be echoed character-for-character", text)
        self.assertIn("paraphrase, normalize, translate, replace, or infer", text)
        self.assertIn("canonical token, never a prose explanation", text)

    def test_inputs_section_identifies_python_supplied_canonical_value(self):
        text = self.normalized
        self.assertIn("Python also supplies the canonical rights_basis value", text)
        self.assertIn("opaque Python-owned token", text)

    def test_ready_example_echoes_canonical_upload_token(self):
        example = json.loads(self.blocks[0])
        self.assertEqual(
            example["rights_basis"], self.CANONICAL_UPLOAD_RIGHTS_BASIS
        )

    def test_refused_example_echoes_canonical_restricted_token(self):
        example = json.loads(self.blocks[1])
        self.assertEqual(
            example["rights_basis"], self.CANONICAL_RESTRICTED_RIGHTS_BASIS
        )

    def test_documented_examples_never_use_prose_rights_basis(self):
        import re

        token_pattern = re.compile(r"^[a-z0-9_]+$")
        for block in self.blocks:
            example = json.loads(block)
            value = example["rights_basis"]
            self.assertIsInstance(value, str)
            self.assertTrue(
                token_pattern.match(value),
                f"rights_basis example is not a canonical token: {value!r}",
            )

    def test_legacy_prose_rights_basis_examples_are_absent(self):
        for legacy in self.LEGACY_PROSE_RIGHTS_BASIS_VALUES:
            self.assertNotIn(
                legacy,
                self.text,
                f"legacy prose rights_basis example still present: {legacy}",
            )

    def test_reminders_include_rights_basis_exact_echo(self):
        text = self.normalized
        self.assertIn("Echo the provided rights_basis value exactly", text)
        self.assertIn(
            "Never paraphrase, translate, or replace it with prose", text
        )


class TestAdaptationAuthorPromptHygiene(unittest.TestCase):
    """Changed files follow the repo ASCII and licensing conventions."""

    def test_changed_files_are_ascii_only(self):
        for path in (PROMPT_PATH, Path(__file__)):
            text = path.read_text(encoding="utf-8")
            non_ascii = [ch for ch in text if ord(ch) >= 128]
            self.assertEqual(non_ascii, [], f"non-ASCII characters in {path}")

    def test_test_file_has_spdx_header(self):
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertIn("SPDX-FileCopyrightText", text)
        self.assertIn("SPDX-License-Identifier", text)


if __name__ == "__main__":
    unittest.main()
