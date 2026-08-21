"""
Tests for scanner.license_scancode.LicenseChecker.

scancode is invoked as a CLI subprocess and never imported, so these tests mock
subprocess.run and the JSON file it writes. That keeps the suite fast and avoids
depending on the multi-hundred-megabyte scancode-toolkit package.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch as mock_patch

from scanner.copyright_checker import DEFAULT_INTERNAL_ENTITIES
from scanner.license_scancode import (
    LicenseChecker,
    PROPRIETARY_LICENSE,
    split_license_components,
)

PERMISSIVE = [
    "BSD-3-Clause",
    "BSD-3-Clause-Clear",
    "MIT",
    "Apache-2.0",
    "ISC",
    "LicenseRef-scancode-unicode",
]

COPYLEFT = [
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
]


def make_patch_obj(changes: list) -> MagicMock:
    """
    Build a stub Patch exposing only the .changes attribute.

    Args:
        changes: List of change dictionaries.

    Returns:
        A stub object with a .changes attribute.
    """
    stub = MagicMock()
    stub.changes = changes
    return stub


def make_change(
    content: str,
    change_type: str = "MODIFIED",
    path_name: str = "src/foo.c",
    file_type: str = "source",
) -> dict:
    """
    Build a single change dictionary in the shape Patch produces.

    Args:
        content: Diff content for the file.
        change_type: One of ADDED/MODIFIED/DELETED/RENAMED.
        path_name: File path.
        file_type: Either 'source' or 'binary'.

    Returns:
        A change dictionary.
    """
    return {
        "path_name": path_name,
        "file_type": file_type,
        "change_type": change_type,
        "content": content,
    }


class ScancodeMockMixin:
    """Provides a subprocess.run replacement that writes a fake scancode report."""

    def install_scancode_mock(self, detections: dict):
        """
        Patch subprocess.run so it writes a scancode-shaped JSON report.

        Args:
            detections: Maps scanned filename (e.g. '0_added.txt') to either an
                SPDX expression string, or None for 'no license detected'.
        """

        def fake_run(cmd, **_kwargs):
            output_file = cmd[cmd.index("--json-pp") + 1]
            files = []
            for filename, expression in detections.items():
                entry = {"path": filename, "type": "file", "license_detections": []}
                if expression is not None:
                    entry["license_detections"] = [{"license_expression_spdx": expression}]
                files.append(entry)
            # scancode also reports the containing directory; run() must skip it.
            files.append({"path": ".", "type": "directory", "license_detections": []})
            Path(output_file).write_text(json.dumps({"files": files}), encoding="utf-8")
            return MagicMock(returncode=0)

        patcher = mock_patch("scanner.license_scancode.subprocess.run", side_effect=fake_run)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestSplitLicenseComponents(unittest.TestCase):
    """
    split_license_components enables component-level checks that a
    whole-expression evaluation would miss (e.g. spotting the proprietary
    marker inside a compound expression).
    """

    def test_single_license(self):
        """A lone identifier yields a one-element list."""
        self.assertEqual(split_license_components("MIT"), ["MIT"])

    def test_and_expression_is_split(self):
        """AND-joined components are separated."""
        self.assertEqual(split_license_components("MIT AND Apache-2.0"), ["MIT", "Apache-2.0"])

    def test_or_expression_is_split(self):
        """OR-joined components are separated."""
        self.assertEqual(split_license_components("MIT OR GPL-2.0-only"), ["MIT", "GPL-2.0-only"])

    def test_parentheses_are_stripped(self):
        """Grouping parentheses do not leak into component names."""
        self.assertEqual(
            split_license_components("(MIT OR GPL-2.0-only) AND Apache-2.0"),
            ["MIT", "GPL-2.0-only", "Apache-2.0"],
        )

    def test_empty_expression_yields_empty_list(self):
        """An empty expression yields no components."""
        self.assertEqual(split_license_components(""), [])


class TestIsLicensePermissive(unittest.TestCase):
    """The SPDX expression evaluator."""

    def setUp(self):
        """Create a checker whose allowed list is the permissive set."""
        self.checker = LicenseChecker(make_patch_obj([]), "org/repo", PERMISSIVE)

    def test_single_permissive_license(self):
        """A lone permissive identifier is permissive."""
        self.assertTrue(self.checker.is_license_permissive("MIT"))

    def test_single_copyleft_license(self):
        """A lone copyleft identifier is not permissive."""
        self.assertFalse(self.checker.is_license_permissive("GPL-2.0-only"))

    def test_whitespace_is_stripped(self):
        """Surrounding whitespace does not affect evaluation."""
        self.assertTrue(self.checker.is_license_permissive("  MIT  "))

    def test_and_requires_all_permissive(self):
        """Every component of an AND expression must be permissive."""
        self.assertTrue(self.checker.is_license_permissive("MIT AND Apache-2.0"))
        self.assertFalse(self.checker.is_license_permissive("MIT AND GPL-2.0-only"))

    def test_or_requires_at_least_one_permissive(self):
        """An OR group passes when any single option is permissive."""
        self.assertTrue(self.checker.is_license_permissive("(MIT OR GPL-2.0-only)"))
        self.assertFalse(self.checker.is_license_permissive("(GPL-2.0-only OR GPL-3.0-only)"))

    def test_leading_or_group_short_circuits(self):
        """
        A leading '(X OR Y) AND ...' dual-license expression is decided solely by
        the leading OR group; trailing AND terms are treated as comment noise.
        """
        self.assertTrue(
            self.checker.is_license_permissive("(MIT OR GPL-2.0-only) AND GPL-3.0-only")
        )

    def test_unknown_license_is_not_permissive(self):
        """An identifier absent from the allowed list is not permissive."""
        self.assertFalse(self.checker.is_license_permissive("LicenseRef-scancode-unknown"))


class TestGplOrLaterCompatibility(unittest.TestCase):
    """GPL '-or-later' backward compatibility against a copyleft project."""

    def setUp(self):
        """Create a checker whose allowed list is the copyleft set."""
        self.checker = LicenseChecker(make_patch_obj([]), "org/repo", COPYLEFT)

    def test_or_later_accepts_only_variant(self):
        """A project allowing GPL-2.0-or-later also accepts GPL-2.0-only."""
        self.assertTrue(self.checker.is_license_permissive("GPL-2.0-only"))

    def test_or_later_accepts_bare_base_license(self):
        """The bare base identifier is accepted too."""
        checker = LicenseChecker(make_patch_obj([]), "org/repo", ["GPL-2.0-or-later"])
        self.assertTrue(checker.is_license_permissive("GPL-2.0"))

    def test_permissive_project_rejects_gpl(self):
        """A permissive project does not accept GPL via this path."""
        checker = LicenseChecker(make_patch_obj([]), "org/repo", PERMISSIVE)
        self.assertFalse(checker.is_license_permissive("GPL-2.0-only"))


class TestIsSourceFile(unittest.TestCase):
    """Source-file extension detection."""

    def setUp(self):
        """Create a checker with an empty patch."""
        self.checker = LicenseChecker(make_patch_obj([]), "org/repo", PERMISSIVE)

    def test_known_source_extensions(self):
        """Recognized code extensions are source files."""
        for name in (
            "a.c",
            "a.cpp",
            "a.h",
            "a.hpp",
            "a.java",
            "a.py",
            "a.js",
            "a.ts",
            "a.rb",
            "a.go",
            "a.swift",
            "a.kt",
            "a.kts",
            "a.sh",
        ):
            self.assertTrue(self.checker.is_source_file(name), name)

    def test_non_source_extensions(self):
        """Other extensions are not source files."""
        for name in ("a.txt", "a.cfg", "a.png", "Makefile"):
            self.assertFalse(self.checker.is_source_file(name), name)


class TestLicenseCheckerModePlumbing(unittest.TestCase):
    """
    Constructor defaults for mode/proprietary_entities. run()'s behavior does
    not yet branch on mode -- that lands in a later commit -- so this only
    covers the plumbing itself.
    """

    def test_mode_defaults_to_opensource(self):
        """With no mode argument, the checker defaults to opensource."""
        checker = LicenseChecker(make_patch_obj([]), "org/repo", PERMISSIVE)
        self.assertEqual(checker.mode, "opensource")

    def test_proprietary_entities_defaults_to_module_default(self):
        """With no proprietary_entities argument, the module default is used."""
        checker = LicenseChecker(make_patch_obj([]), "org/repo", PERMISSIVE)
        self.assertEqual(checker.proprietary_entities, DEFAULT_INTERNAL_ENTITIES)

    def test_mode_and_entities_are_stored_when_provided(self):
        """Explicit mode/proprietary_entities arguments are stored as given."""
        checker = LicenseChecker(
            make_patch_obj([]),
            "org/repo",
            PERMISSIVE,
            mode="proprietary",
            proprietary_entities=["Acme Robotics"],
        )
        self.assertEqual(checker.mode, "proprietary")
        self.assertEqual(checker.proprietary_entities, ["Acme Robotics"])


class TestDetectLicensesBatch(ScancodeMockMixin, unittest.TestCase):
    """Batch scanning splits added and deleted lines into separate scans."""

    def test_added_and_deleted_are_scanned_separately(self):
        """Added and deleted line groups get independent results."""
        self.install_scancode_mock({"0_added.txt": "MIT", "0_deleted.txt": "BSD-3-Clause"})
        checker = LicenseChecker(make_patch_obj([]), "org/repo", PERMISSIVE)
        results = checker.detect_licenses_batch(
            [make_change("+MIT license text\n-BSD license text\n")]
        )
        self.assertEqual(results[(0, "added")], "MIT")
        self.assertEqual(results[(0, "deleted")], "BSD-3-Clause")

    def test_empty_content_is_skipped(self):
        """A change with no content produces no scan results."""
        self.install_scancode_mock({})
        checker = LicenseChecker(make_patch_obj([]), "org/repo", PERMISSIVE)
        self.assertEqual(checker.detect_licenses_batch([make_change(None)]), {})

    def test_no_detection_omits_entry(self):
        """A scanned file with no license detections yields a falsy result."""
        self.install_scancode_mock({"0_added.txt": None})
        checker = LicenseChecker(make_patch_obj([]), "org/repo", PERMISSIVE)
        results = checker.detect_licenses_batch([make_change("+just some code\n")])
        self.assertFalse(results.get((0, "added")))


class TestRunLicenseRules(ScancodeMockMixin, unittest.TestCase):
    """End-to-end rule evaluation in run()."""

    def run_checker(self, changes: list, detections: dict, allowed: list = None) -> dict:
        """
        Install the scancode mock and run the checker.

        Args:
            changes: Change dictionaries to evaluate.
            detections: Filename -> SPDX expression (or None) mapping.
            allowed: Allowed license list; defaults to the permissive set.

        Returns:
            The flagged-files dictionary (the warning half of the returned
            tuple is not exercised by these tests, which cover opensource-mode
            behavior only).
        """
        self.install_scancode_mock(detections)
        checker = LicenseChecker(make_patch_obj(changes), "org/repo", allowed or PERMISSIVE)
        flagged, _warnings = checker.run()
        return flagged

    def test_incompatible_license_added_is_flagged(self):
        """Adding a copyleft license to a permissive repo is flagged."""
        flagged = self.run_checker([make_change("+GPL text\n")], {"0_added.txt": "GPL-2.0-only"})
        self.assertIn("Incompatible license added: GPL-2.0-only", flagged["src/foo.c"][0])

    def test_permissive_license_added_is_not_flagged(self):
        """Adding a permissive license to a permissive repo is allowed."""
        flagged = self.run_checker([make_change("+MIT text\n")], {"0_added.txt": "MIT"})
        self.assertEqual(flagged, {})

    def test_license_deleted_without_replacement_is_flagged(self):
        """Removing a license with nothing added is flagged."""
        flagged = self.run_checker([make_change("-MIT text\n")], {"0_deleted.txt": "MIT"})
        self.assertIn("License deleted: MIT", flagged["src/foo.c"][0])

    def test_license_changed_to_copyleft_is_flagged(self):
        """Swapping a permissive license for a copyleft one is flagged."""
        flagged = self.run_checker(
            [make_change("+GPL text\n-MIT text\n")],
            {"0_added.txt": "GPL-2.0-only", "0_deleted.txt": "MIT"},
        )
        self.assertIn(
            "License deleted: MIT and license added: GPL-2.0-only", flagged["src/foo.c"][0]
        )

    def test_license_changed_to_permissive_is_allowed(self):
        """Swapping one permissive license for another is allowed."""
        flagged = self.run_checker(
            [make_change("+Apache text\n-MIT text\n")],
            {"0_added.txt": "Apache-2.0", "0_deleted.txt": "MIT"},
        )
        self.assertEqual(flagged, {})

    def test_new_source_file_without_license_is_flagged(self):
        """An ADDED source file with no detected license is flagged."""
        flagged = self.run_checker(
            [make_change("+int main(void) { return 0; }\n", change_type="ADDED")],
            {"0_added.txt": None},
        )
        self.assertIn("No license added for source file", flagged["src/foo.c"][0])

    def test_new_non_source_file_without_license_is_not_flagged(self):
        """An ADDED non-source file with no license is not flagged."""
        flagged = self.run_checker(
            [make_change("+some data\n", change_type="ADDED", path_name="data/blob.txt")],
            {"0_added.txt": None},
        )
        self.assertEqual(flagged, {})

    def test_binary_changes_are_skipped(self):
        """Binary changes are excluded before scanning."""
        flagged = self.run_checker([make_change("+data\n", file_type="binary")], {})
        self.assertEqual(flagged, {})

    def test_no_source_files_returns_empty(self):
        """With no source changes, run() short-circuits."""
        checker = LicenseChecker(make_patch_obj([]), "org/repo", PERMISSIVE)
        self.assertEqual(checker.run(), ({}, {}))

    def test_run_returns_a_flagged_warning_tuple(self):
        """
        run() returns (flagged_files, warning_files). A known incompatible
        license like GPL-2.0-only is never classified as uncertain, so it
        lands in flagged_files and warning_files stays empty.
        """
        self.install_scancode_mock({"0_added.txt": "GPL-2.0-only"})
        checker = LicenseChecker(
            make_patch_obj([make_change("+GPL text\n")]), "org/repo", PERMISSIVE
        )
        flagged, warnings = checker.run()
        self.assertIn("src/foo.c", flagged)
        self.assertEqual(warnings, {})


class TestRunProprietaryMode(ScancodeMockMixin, unittest.TestCase):
    """
    Proprietary-mode rule modifiers. mode="opensource" behavior is covered by
    TestRunLicenseRules and is unaffected by any of this.
    """

    def run_checker(
        self, changes: list, detections: dict, allowed: list = None, entities: list = None
    ) -> tuple:
        """
        Install the scancode mock and run the checker in proprietary mode.

        Args:
            changes: Change dictionaries to evaluate.
            detections: Filename -> SPDX expression (or None) mapping.
            allowed: Allowed license list; defaults to the permissive set
                (main.py passes the canonical PERMISSIVE_LICENSES here in
                real proprietary-mode runs).
            entities: Internal-entity override; defaults to the module default.

        Returns:
            The (flagged, warning) tuple.
        """
        self.install_scancode_mock(detections)
        checker = LicenseChecker(
            make_patch_obj(changes),
            "org/repo",
            allowed or PERMISSIVE,
            mode="proprietary",
            proprietary_entities=entities,
        )
        return checker.run()

    def test_permissive_addition_is_a_warning_not_a_block(self):
        """A permissive OSS addition warns instead of blocking."""
        flagged, warnings = self.run_checker(
            [make_change("+MIT text\n", change_type="ADDED")], {"0_added.txt": "MIT"}
        )
        self.assertEqual(flagged, {})
        self.assertIn("Permissive open-source license added: MIT", warnings["src/foo.c"][0])

    def test_permissive_warning_includes_notice_reminder(self):
        """The permissive-addition warning reminds the author to update NOTICE."""
        _flagged, warnings = self.run_checker(
            [make_change("+MIT text\n", change_type="ADDED")], {"0_added.txt": "MIT"}
        )
        self.assertIn("NOTICE", warnings["src/foo.c"][0])

    def test_permissive_license_change_is_also_a_warning(self):
        """An existing file's license changing to a permissive one also warns."""
        _flagged, warnings = self.run_checker(
            [make_change("+MIT text\n-BSD-3-Clause text\n")],
            {"0_added.txt": "MIT", "0_deleted.txt": "BSD-3-Clause"},
        )
        self.assertIn("Permissive open-source license added: MIT", warnings["src/foo.c"][0])

    def test_unchanged_permissive_license_does_not_warn(self):
        """An unchanged license (identical on both sides) does not warn."""
        _flagged, warnings = self.run_checker(
            [make_change("+MIT text\n-MIT text\n")],
            {"0_added.txt": "MIT", "0_deleted.txt": "MIT"},
        )
        self.assertEqual(warnings, {})

    def test_removing_proprietary_marking_is_an_error(self):
        """
        Removing a proprietary rights statement blocks, even when a permissive
        license replaces it -- losing the marking is the compliance-relevant
        event regardless of what takes its place.
        """
        flagged, warnings = self.run_checker(
            [make_change("+MIT text\n-proprietary text\n")],
            {"0_added.txt": "MIT", "0_deleted.txt": PROPRIETARY_LICENSE},
        )
        self.assertIn("Proprietary license statement removed", flagged["src/foo.c"][0])
        self.assertEqual(warnings, {})

    def test_removing_proprietary_marking_with_no_replacement_is_an_error(self):
        """Deleting the proprietary statement outright also blocks."""
        flagged, _warnings = self.run_checker(
            [make_change("-proprietary text\n")], {"0_deleted.txt": PROPRIETARY_LICENSE}
        )
        self.assertIn("Proprietary license statement removed", flagged["src/foo.c"][0])

    def test_removing_proprietary_marker_from_compound_expression_is_an_error(self):
        """The marker being one component of a compound deleted expression still counts."""
        flagged, _warnings = self.run_checker(
            [make_change("+MIT text\n-mixed text\n")],
            {"0_added.txt": "MIT", "0_deleted.txt": f"{PROPRIETARY_LICENSE} AND GPL-2.0-only"},
        )
        self.assertIn("Proprietary license statement removed", flagged["src/foo.c"][0])

    def test_permissive_added_while_proprietary_retained_is_a_warning(self):
        """
        Adding a permissive license to a file that keeps its proprietary
        marking warns rather than blocking: the retained marker is expected,
        so it must not fail the "all AND components permissive" rule.
        """
        flagged, warnings = self.run_checker(
            [make_change("+MIT text\n-proprietary text\n")],
            {"0_added.txt": f"MIT AND {PROPRIETARY_LICENSE}", "0_deleted.txt": PROPRIETARY_LICENSE},
        )
        self.assertEqual(flagged, {})
        self.assertIn("Permissive open-source license added", warnings["src/foo.c"][0])

    def test_copyleft_added_while_proprietary_retained_still_blocks(self):
        """Excluding the retained marker does not excuse a copyleft addition."""
        flagged, warnings = self.run_checker(
            [make_change("+GPL text\n-proprietary text\n")],
            {
                "0_added.txt": f"GPL-2.0-only AND {PROPRIETARY_LICENSE}",
                "0_deleted.txt": PROPRIETARY_LICENSE,
            },
        )
        self.assertIn("src/foo.c", flagged)
        self.assertEqual(warnings, {})

    def test_unchanged_proprietary_marking_is_silent(self):
        """A proprietary marking present identically on both sides is not a removal."""
        flagged, warnings = self.run_checker(
            [make_change("+proprietary text\n-proprietary text\n")],
            {"0_added.txt": PROPRIETARY_LICENSE, "0_deleted.txt": PROPRIETARY_LICENSE},
        )
        self.assertEqual(flagged, {})
        self.assertEqual(warnings, {})

    def test_opensource_mode_does_not_flag_proprietary_removal_specially(self):
        """
        The proprietary-removal rule is proprietary-mode only. In opensource
        mode the same diff follows the pre-existing generic license rules.
        """
        self.install_scancode_mock(
            {"0_added.txt": "MIT", "0_deleted.txt": PROPRIETARY_LICENSE},
        )
        checker = LicenseChecker(
            make_patch_obj([make_change("+MIT text\n-proprietary text\n")]),
            "org/repo",
            PERMISSIVE,
            mode="opensource",
        )
        flagged, warnings = checker.run()
        self.assertEqual(flagged, {})
        self.assertEqual(warnings, {})

    def test_copyleft_addition_still_blocks(self):
        """Copyleft additions are unaffected and still block."""
        flagged, warnings = self.run_checker(
            [make_change("+GPL text\n", change_type="ADDED")], {"0_added.txt": "GPL-2.0-only"}
        )
        self.assertIn("Incompatible license added: GPL-2.0-only", flagged["src/foo.c"][0])
        self.assertEqual(warnings, {})

    def test_solitary_proprietary_license_is_silent(self):
        """A solitary proprietary-license detection raises no issue at all."""
        flagged, warnings = self.run_checker(
            [make_change("+proprietary header\n", change_type="ADDED")],
            {"0_added.txt": "LicenseRef-scancode-proprietary-license"},
        )
        self.assertEqual(flagged, {})
        self.assertEqual(warnings, {})

    def test_new_file_with_internal_copyright_and_no_license_is_not_blocked(self):
        """A Qualcomm-copyrighted new file with no detected license is not blocked."""
        content = "+Copyright (c) 2024 Qualcomm Technologies, Inc.\n+int main(void) {}\n"
        flagged, warnings = self.run_checker(
            [make_change(content, change_type="ADDED")], {"0_added.txt": None}
        )
        self.assertEqual(flagged, {})
        self.assertEqual(warnings, {})

    def test_new_file_with_custom_entity_and_no_license_is_not_blocked(self):
        """A configured custom entity is honored in place of the defaults."""
        content = "+Copyright (c) 2024 Acme Robotics\n+int main(void) {}\n"
        flagged, _warnings = self.run_checker(
            [make_change(content, change_type="ADDED")],
            {"0_added.txt": None},
            entities=["Acme Robotics"],
        )
        self.assertEqual(flagged, {})

    def test_new_file_with_no_copyright_and_no_license_is_blocked_distinctly(self):
        """
        A new file with neither a license nor a recognized internal copyright
        is still blocked, with a message distinct from the opensource one.
        """
        content = "+int main(void) {}\n"
        flagged, _warnings = self.run_checker(
            [make_change(content, change_type="ADDED")], {"0_added.txt": None}
        )
        message = flagged["src/foo.c"][0]
        self.assertIn("scan team/legal", message)
        self.assertNotEqual(message, "No license added for source file: src/foo.c")

    def test_opensource_message_is_unchanged(self):
        """The opensource-mode message for the same scenario is the original generic one."""
        self.install_scancode_mock({"0_added.txt": None})
        checker = LicenseChecker(
            make_patch_obj([make_change("+int main(void) {}\n", change_type="ADDED")]),
            "org/repo",
            PERMISSIVE,
            mode="opensource",
        )
        flagged, _warnings = checker.run()
        self.assertEqual(flagged["src/foo.c"], ["No license added for source file: src/foo.c"])


class TestRunChangeTypeCoverageGaps(ScancodeMockMixin, unittest.TestCase):
    """
    Documents pre-existing gaps: license rules apply only to MODIFIED and ADDED
    changes. DELETED and RENAMED changes are never license-checked. These assert
    current behavior, not desired behavior.
    """

    def test_deleted_change_type_is_not_license_checked(self):
        """Deleting a file removes its license without being flagged."""
        self.install_scancode_mock({"0_deleted.txt": "MIT"})
        checker = LicenseChecker(
            make_patch_obj([make_change("-MIT text\n", change_type="DELETED")]),
            "org/repo",
            PERMISSIVE,
        )
        self.assertEqual(checker.run(), ({}, {}))

    def test_renamed_change_type_is_not_license_checked(self):
        """RENAMED changes are not license-checked."""
        self.install_scancode_mock({"0_deleted.txt": "MIT"})
        checker = LicenseChecker(
            make_patch_obj([make_change("-MIT text\n", change_type="RENAMED")]),
            "org/repo",
            PERMISSIVE,
        )
        self.assertEqual(checker.run(), ({}, {}))


class TestLicenseComparisonFix(ScancodeMockMixin, unittest.TestCase):
    """
    Regression test for a fixed string/list type confusion at
    license_scancode.py:229. detect_licenses_batch returns license expressions
    as strings, but run() used to compare them with set(added) != set(deleted)
    -- comparing sets of *characters*, not licenses, so anagram pairs like
    'MIT'/'TIM' compared equal. Now compared as plain strings.
    """

    def test_anagram_licenses_are_treated_as_a_real_change(self):
        """'MIT' and 'TIM' are not the same license and must be flagged as such."""
        self.install_scancode_mock({"0_added.txt": "TIM", "0_deleted.txt": "MIT"})
        checker = LicenseChecker(
            make_patch_obj([make_change("+TIM text\n-MIT text\n")]),
            "org/repo",
            PERMISSIVE,
        )
        flagged, _warnings = checker.run()
        self.assertIn("License deleted: MIT and license added: TIM", flagged["src/foo.c"][0])


if __name__ == "__main__":
    unittest.main()
