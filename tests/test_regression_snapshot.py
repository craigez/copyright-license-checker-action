"""
Step 0 regression harness (see CODE_REVIEW.md).

Snapshots main()'s end-to-end stdout + exit code -- exercising the real
Patch, LicenseChecker and CopyrightChecker, with only the scancode
subprocess mocked -- for one fixture patch per COMPLIANCE.md scenario, in
whichever mode(s) apply. This pins CURRENT behavior, including two known
bugs, as a baseline: Steps 1 and 2 of the refactor plan are only safe if
their fix is the *only* diff against these snapshots, so every other
scenario here must keep matching byte-for-byte through those steps.

BUG-1 (fixed): the proprietary-removal message was misclassified as a
warning instead of a blocking error by main.is_uncertain_license_issue()'s
string-parsing catch-all (it contains "LicenseRef-scancode-", so it matched
the generic uncertain-license rule). Severity is now decided once, at
creation time, inside LicenseChecker.run() -- see
TestProprietaryModeScenarios.test_pm1_proprietary_removal_blocks below.

BUG-2 (fixed): sys.exit(len(flagged_files)) truncated to 0 at exactly 256
flagged files (POSIX exit statuses are 8-bit). main() now exits 1 for any
blocking issue regardless of file count -- see
TestBug2ExitCodeTruncation.test_256_flagged_files_exits_nonzero below.

BUG-3 (fixed): in proprietary mode, deleting a permissive license and adding
a proprietary marking in its place reported nothing at all, because the
"solitary proprietary detection is expected" rule ignored the deleted side.
The skip now also requires that the deleted side gives up no license of its
own -- see
TestProprietaryModeScenarios.test_pm8_permissive_swapped_for_proprietary_blocks
and the pm9/pm10 cases below.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch as mock_patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402  pylint: disable=wrong-import-position
from tests.static_data import patches  # noqa: E402  pylint: disable=wrong-import-position

PROPRIETARY_LICENSE = "LicenseRef-scancode-proprietary-license"


def install_scancode_mock(detections: dict):
    """
    Build a subprocess.run replacement that writes a scancode-shaped JSON
    report, keyed by the filenames detect_licenses_batch scans.

    Args:
        detections: Maps scanned filename (e.g. '0_added.txt') to either an
            SPDX expression string, or None for 'no license detected'.

    Returns:
        A mock.patch context manager for scanner.license_scancode.subprocess.run.
    """

    def fake_run(cmd, **_kwargs):
        output_file = cmd[cmd.index("--json-pp") + 1]
        files = []
        for filename, expression in detections.items():
            entry = {"path": filename, "type": "file", "license_detections": []}
            if expression is not None:
                entry["license_detections"] = [{"license_expression_spdx": expression}]
            files.append(entry)
        files.append({"path": ".", "type": "directory", "license_detections": []})
        Path(output_file).write_text(json.dumps({"files": files}), encoding="utf-8")
        return MagicMock(returncode=0)

    return mock_patch("scanner.license_scancode.subprocess.run", side_effect=fake_run)


class RegressionSnapshotTestCase(unittest.TestCase):
    """
    Runs main() end-to-end (real Patch/LicenseChecker/CopyrightChecker, only
    scancode mocked) in a scratch directory with no LICENSE file, so
    opensource-mode scenarios exercise get_license()'s real default-fallback
    path against repo_name "org/repo" (which matches no scanner/config.py
    entry).
    """

    def setUp(self):
        """Run each test in a scratch directory, isolated from any real .licenseignore."""
        # pylint: disable=consider-using-with
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        original_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, original_cwd)

    def run_main(
        self,
        patch_content: str,
        detections: dict,
        mode: str = None,
        proprietary_entities: str = None,
    ) -> tuple:
        """
        Write the patch to disk and run main() end-to-end.

        Args:
            patch_content: Raw patch text.
            detections: Scancode filename -> SPDX expression (or None) mapping.
            mode: Optional --mode value.
            proprietary_entities: Optional --proprietary-entities value.

        Returns:
            Tuple of (captured stdout, exit code).
        """
        patch_path = Path(self.tmp.name, "pr.patch")
        patch_path.write_text(patch_content, encoding="utf-8")

        argv = ["main.py", str(patch_path), "org/repo"]
        if mode:
            argv += ["--mode", mode]
        if proprietary_entities:
            argv += ["--proprietary-entities", proprietary_entities]

        buffer = io.StringIO()
        with install_scancode_mock(detections):
            with mock_patch.object(sys, "argv", argv):
                with contextlib.redirect_stdout(buffer):
                    with self.assertRaises(SystemExit) as caught:
                        main.main()
        return buffer.getvalue(), caught.exception.code


EXPECTED_OS1_COPYLEFT_ADDED_BLOCKS = "< file license/copyright check > License file not found or detection failed, checking config...\n< file license/copyright check > Using default license: BSD-3-Clause-Clear\n< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/module.c\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • Incompatible license added: GPL-2.0-only\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_OS1_COPYLEFT_ADDED_BLOCKS_CODE = 1

EXPECTED_OS2_LICENSE_DELETED_BLOCKS = "< file license/copyright check > License file not found or detection failed, checking config...\n< file license/copyright check > Using default license: BSD-3-Clause-Clear\n< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/utils.py\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • License deleted: MIT\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_OS2_LICENSE_DELETED_BLOCKS_CODE = 1

EXPECTED_OS3_LICENSE_CHANGED_BLOCKS = "< file license/copyright check > License file not found or detection failed, checking config...\n< file license/copyright check > Using default license: BSD-3-Clause-Clear\n< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/core.cpp\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • License deleted: MIT and license added: GPL-2.0-only\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_OS3_LICENSE_CHANGED_BLOCKS_CODE = 1

EXPECTED_OS4_NEW_FILE_NO_LICENSE_BLOCKS = "< file license/copyright check > License file not found or detection failed, checking config...\n< file license/copyright check > Using default license: BSD-3-Clause-Clear\n< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/new_feature.py\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • No license added for source file: src/new_feature.py\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_OS4_NEW_FILE_NO_LICENSE_BLOCKS_CODE = 1

EXPECTED_OS5_COPYRIGHT_DELETION_BLOCKS = "< file license/copyright check > License file not found or detection failed, checking config...\n< file license/copyright check > Using default license: BSD-3-Clause-Clear\n< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/bar.c\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 COPYRIGHT ISSUES:\n< file license/copyright check > │ │  • Copyright deletions detected: [' * Copyright (c) 2019 Some Other Author. All rights reserved.']\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_OS5_COPYRIGHT_DELETION_BLOCKS_CODE = 1

EXPECTED_OS6_UNCERTAIN_LICENSE_WARNS = "< file license/copyright check > License file not found or detection failed, checking config...\n< file license/copyright check > Using default license: BSD-3-Clause-Clear\n< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ ⚠️   W A R N I N G S  (Non-blocking)\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/module.c\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ ⚠️  LICENSE WARNINGS:\n< file license/copyright check > │ │  • Incompatible license added: LicenseRef-scancode-unknown-license-reference\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_OS6_UNCERTAIN_LICENSE_WARNS_CODE = 0

EXPECTED_OS6B_MIXED_UNCERTAIN_AND_GPL_BLOCKS = "< file license/copyright check > License file not found or detection failed, checking config...\n< file license/copyright check > Using default license: BSD-3-Clause-Clear\n< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/module.c\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • Incompatible license added: GPL-2.0-only AND LicenseRef-scancode-unknown-license-reference\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_OS6B_MIXED_UNCERTAIN_AND_GPL_BLOCKS_CODE = 1

EXPECTED_OS7_SOLE_PROPRIETARY_BLOCKS_OPENSOURCE = "< file license/copyright check > License file not found or detection failed, checking config...\n< file license/copyright check > Using default license: BSD-3-Clause-Clear\n< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/module.c\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • Incompatible license added: LicenseRef-scancode-proprietary-license\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_OS7_SOLE_PROPRIETARY_BLOCKS_OPENSOURCE_CODE = 1

EXPECTED_PM1_PROPRIETARY_REMOVAL_BLOCKS = "< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/utils.py\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • Proprietary license statement removed: LicenseRef-scancode-proprietary-license -- removing a proprietary rights statement requires review; restore it, or route the change to the scan team/legal if the file's status has genuinely changed.\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_PM1_PROPRIETARY_REMOVAL_BLOCKS_CODE = 1

EXPECTED_PM2_PERMISSIVE_ADDITION_WARNS = "< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ ⚠️   W A R N I N G S  (Non-blocking)\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/module.c\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ ⚠️  LICENSE WARNINGS:\n< file license/copyright check > │ │  • Permissive open-source license added: MIT -- review that this third-party code is approved for inclusion, and update the repo's NOTICE file with the required attribution.\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_PM2_PERMISSIVE_ADDITION_WARNS_CODE = 0

EXPECTED_PM3_SOLE_PROPRIETARY_SILENT = (
    "< file license/copyright check > ✅ No license or copyright issues detected\n"
)
EXPECTED_PM3_SOLE_PROPRIETARY_SILENT_CODE = 0

EXPECTED_PM4A_INTERNAL_COPYRIGHT_NO_LICENSE_NOT_BLOCKED = (
    "< file license/copyright check > ✅ No license or copyright issues detected\n"
)
EXPECTED_PM4A_INTERNAL_COPYRIGHT_NO_LICENSE_NOT_BLOCKED_CODE = 0

EXPECTED_PM4B_NO_LICENSE_NO_COPYRIGHT_BLOCKS_DISTINCTLY = "< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/new_module.c\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • No license or internal copyright found for source file: src/new_module.c -- if this is third-party code, do NOT add a Qualcomm copyright; route it to the scan team/legal for review. If this is Qualcomm-authored code, add the appropriate copyright marking.\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_PM4B_NO_LICENSE_NO_COPYRIGHT_BLOCKS_DISTINCTLY_CODE = 1

EXPECTED_PM5_COPYLEFT_STILL_BLOCKS = "< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/module.c\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • Incompatible license added: GPL-2.0-only\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_PM5_COPYLEFT_STILL_BLOCKS_CODE = 1

EXPECTED_PM6_COPYRIGHT_DELETION_STILL_BLOCKS = "< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/bar.c\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 COPYRIGHT ISSUES:\n< file license/copyright check > │ │  • Copyright deletions detected: [' * Copyright (c) 2019 Some Other Author. All rights reserved.']\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_PM6_COPYRIGHT_DELETION_STILL_BLOCKS_CODE = 1

EXPECTED_PM7_PROPRIETARY_SWAPPED_FOR_PERMISSIVE_BLOCKS = "< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/core.cpp\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • Proprietary license statement removed: LicenseRef-scancode-proprietary-license -- removing a proprietary rights statement requires review; restore it, or route the change to the scan team/legal if the file's status has genuinely changed.\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_PM7_PROPRIETARY_SWAPPED_FOR_PERMISSIVE_BLOCKS_CODE = 1

EXPECTED_PM8_PERMISSIVE_SWAPPED_FOR_PROPRIETARY_BLOCKS = "< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/core.cpp\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • License deleted: MIT and license added: LicenseRef-scancode-proprietary-license\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_PM8_PERMISSIVE_SWAPPED_FOR_PROPRIETARY_BLOCKS_CODE = 1

EXPECTED_PM9_MARKER_STRIPPED_FROM_COMPOUND_BLOCKS = "< file license/copyright check > ┌───────────────────────────────────────────┐\n< file license/copyright check > │           **Flagged Files Report**         │\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ 📖 For more information, see: COMPLIANCE.md\n< file license/copyright check > │    https://github.com/qualcomm/copyright-license-checker-action/blob/main/COMPLIANCE.md\n< file license/copyright check > ├───────────────────────────────────────────┤\n< file license/copyright check > │\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │ 🚨  B L O C K I N G   E R R O R S\n< file license/copyright check > │ ═══════════════════════════════════════════\n< file license/copyright check > │\n< file license/copyright check > │ ┌─ 📄 F I L E: src/core.cpp\n< file license/copyright check > │ │\n< file license/copyright check > │ ├─ 🚨 LICENSE ISSUES:\n< file license/copyright check > │ │  • License deleted: MIT AND LicenseRef-scancode-proprietary-license and license added: LicenseRef-scancode-proprietary-license\n< file license/copyright check > │ └─────────────────────────────────────────\n< file license/copyright check > └───────────────────────────────────────────┘\n"  # noqa: E501
EXPECTED_PM9_MARKER_STRIPPED_FROM_COMPOUND_BLOCKS_CODE = 1

EXPECTED_PM10_PROPRIETARY_MARKING_REFORMATTED_SILENT = (
    "< file license/copyright check > ✅ No license or copyright issues detected\n"
)
EXPECTED_PM10_PROPRIETARY_MARKING_REFORMATTED_SILENT_CODE = 0


class TestOpensourceModeScenarios(RegressionSnapshotTestCase):
    """COMPLIANCE.md scenarios 1-7, mode: opensource (the default)."""

    def test_os1_incompatible_license_added_blocks(self):
        """Scenario 1: adding a copyleft license to a permissive repo blocks."""
        output, code = self.run_main(patches.ADDITION_ONLY, {"0_added.txt": "GPL-2.0-only"})
        self.assertEqual(code, EXPECTED_OS1_COPYLEFT_ADDED_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_OS1_COPYLEFT_ADDED_BLOCKS)

    def test_os2_license_deleted_without_replacement_blocks(self):
        """Scenario 2: removing a license with nothing added back blocks."""
        output, code = self.run_main(patches.DELETION_ONLY, {"0_deleted.txt": "MIT"})
        self.assertEqual(code, EXPECTED_OS2_LICENSE_DELETED_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_OS2_LICENSE_DELETED_BLOCKS)

    def test_os3_license_change_to_incompatible_blocks(self):
        """Scenario 3: swapping a permissive license for a copyleft one blocks."""
        output, code = self.run_main(
            patches.ADDITION_AND_DELETION,
            {"0_added.txt": "GPL-2.0-only", "0_deleted.txt": "MIT"},
        )
        self.assertEqual(code, EXPECTED_OS3_LICENSE_CHANGED_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_OS3_LICENSE_CHANGED_BLOCKS)

    def test_os4_missing_license_on_new_source_file_blocks(self):
        """Scenario 4: a new source file with no detected license blocks."""
        output, code = self.run_main(patches.NEW_FILE_NO_LICENSE, {"0_added.txt": None})
        self.assertEqual(code, EXPECTED_OS4_NEW_FILE_NO_LICENSE_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_OS4_NEW_FILE_NO_LICENSE_BLOCKS)

    def test_os5_copyright_deletion_blocks(self):
        """Scenario 5: a copyright statement deleted without replacement blocks."""
        output, code = self.run_main(
            patches.MODIFIED_WITH_DELETED_COPYRIGHT, {"0_deleted.txt": None}
        )
        self.assertEqual(code, EXPECTED_OS5_COPYRIGHT_DELETION_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_OS5_COPYRIGHT_DELETION_BLOCKS)

    def test_os6_uncertain_license_is_a_warning(self):
        """Uncertain/unknown license detection: a lone unknown reference warns."""
        output, code = self.run_main(
            patches.ADDITION_ONLY,
            {"0_added.txt": "LicenseRef-scancode-unknown-license-reference"},
        )
        self.assertEqual(code, EXPECTED_OS6_UNCERTAIN_LICENSE_WARNS_CODE)
        self.assertEqual(output, EXPECTED_OS6_UNCERTAIN_LICENSE_WARNS)

    def test_os6b_mixed_uncertain_and_known_incompatible_blocks(self):
        """Mixed with a known incompatible license, the expression still blocks."""
        output, code = self.run_main(
            patches.ADDITION_ONLY,
            {"0_added.txt": "GPL-2.0-only AND LicenseRef-scancode-unknown-license-reference"},
        )
        self.assertEqual(code, EXPECTED_OS6B_MIXED_UNCERTAIN_AND_GPL_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_OS6B_MIXED_UNCERTAIN_AND_GPL_BLOCKS)

    def test_os7_sole_proprietary_license_blocks_in_opensource_mode(self):
        """Special case: a solitary proprietary-license detection blocks in opensource mode."""
        output, code = self.run_main(patches.ADDITION_ONLY, {"0_added.txt": PROPRIETARY_LICENSE})
        self.assertEqual(code, EXPECTED_OS7_SOLE_PROPRIETARY_BLOCKS_OPENSOURCE_CODE)
        self.assertEqual(output, EXPECTED_OS7_SOLE_PROPRIETARY_BLOCKS_OPENSOURCE)


class TestProprietaryModeScenarios(RegressionSnapshotTestCase):
    """Proprietary Mode section of COMPLIANCE.md."""

    def test_pm1_proprietary_removal_blocks(self):
        """
        BUG-1 (fixed): removing a proprietary rights statement blocks per
        COMPLIANCE.md #1. LicenseChecker.run() classifies severity once, at
        creation time, so this message stays in flagged_files instead of
        being reclassified as a warning by prose-matching downstream.
        """
        output, code = self.run_main(
            patches.DELETION_ONLY, {"0_deleted.txt": PROPRIETARY_LICENSE}, mode="proprietary"
        )
        self.assertEqual(code, EXPECTED_PM1_PROPRIETARY_REMOVAL_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_PM1_PROPRIETARY_REMOVAL_BLOCKS)

    def test_pm2_permissive_addition_is_a_warning_with_notice_reminder(self):
        """#2: adding permissive OSS code warns (with a NOTICE-file reminder), not blocks."""
        output, code = self.run_main(
            patches.ADDITION_ONLY, {"0_added.txt": "MIT"}, mode="proprietary"
        )
        self.assertEqual(code, EXPECTED_PM2_PERMISSIVE_ADDITION_WARNS_CODE)
        self.assertEqual(output, EXPECTED_PM2_PERMISSIVE_ADDITION_WARNS)

    def test_pm3_sole_proprietary_license_is_silent(self):
        """#3: a solitary proprietary-license detection raises no issue at all."""
        output, code = self.run_main(
            patches.ADDITION_ONLY, {"0_added.txt": PROPRIETARY_LICENSE}, mode="proprietary"
        )
        self.assertEqual(code, EXPECTED_PM3_SOLE_PROPRIETARY_SILENT_CODE)
        self.assertEqual(output, EXPECTED_PM3_SOLE_PROPRIETARY_SILENT)

    def test_pm4a_new_file_with_internal_copyright_and_no_license_is_not_blocked(self):
        """#4: a Qualcomm-copyrighted new file with no detected license is not blocked."""
        output, code = self.run_main(
            patches.NEW_FILE_WITH_INTERNAL_COPYRIGHT_NO_LICENSE,
            {"0_added.txt": None},
            mode="proprietary",
        )
        self.assertEqual(code, EXPECTED_PM4A_INTERNAL_COPYRIGHT_NO_LICENSE_NOT_BLOCKED_CODE)
        self.assertEqual(output, EXPECTED_PM4A_INTERNAL_COPYRIGHT_NO_LICENSE_NOT_BLOCKED)

    def test_pm4b_new_file_with_no_license_and_no_copyright_blocks_distinctly(self):
        """#4: with neither a license nor a recognized internal copyright, it still blocks."""
        output, code = self.run_main(
            patches.NEW_FILE_NO_LICENSE_NO_COPYRIGHT, {"0_added.txt": None}, mode="proprietary"
        )
        self.assertEqual(code, EXPECTED_PM4B_NO_LICENSE_NO_COPYRIGHT_BLOCKS_DISTINCTLY_CODE)
        self.assertEqual(output, EXPECTED_PM4B_NO_LICENSE_NO_COPYRIGHT_BLOCKS_DISTINCTLY)

    def test_pm5_copyleft_addition_still_blocks(self):
        """Copyleft is unaffected by proprietary mode and still blocks."""
        output, code = self.run_main(
            patches.ADDITION_ONLY, {"0_added.txt": "GPL-2.0-only"}, mode="proprietary"
        )
        self.assertEqual(code, EXPECTED_PM5_COPYLEFT_STILL_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_PM5_COPYLEFT_STILL_BLOCKS)

    def test_pm6_copyright_deletion_still_blocks(self):
        """Copyright deletion rules are unaffected by proprietary mode and still block."""
        output, code = self.run_main(
            patches.MODIFIED_WITH_DELETED_COPYRIGHT, {"0_deleted.txt": None}, mode="proprietary"
        )
        self.assertEqual(code, EXPECTED_PM6_COPYRIGHT_DELETION_STILL_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_PM6_COPYRIGHT_DELETION_STILL_BLOCKS)

    def test_pm7_proprietary_swapped_for_permissive_blocks_without_notice_warning(self):
        """
        Swap direction 1 -- proprietary marking deleted, permissive OSS license
        added in its place. #1 (proprietary removal blocks) takes precedence
        over #2 (permissive addition warns): the report carries only the
        blocking removal message, and the NOTICE-attribution reminder that a
        bare MIT addition would produce is deliberately suppressed so the
        report is not muddied. Contrast test_pm2, where the same MIT addition
        with nothing deleted warns and exits 0.
        """
        output, code = self.run_main(
            patches.ADDITION_AND_DELETION,
            {"0_added.txt": "MIT", "0_deleted.txt": PROPRIETARY_LICENSE},
            mode="proprietary",
        )
        self.assertEqual(code, EXPECTED_PM7_PROPRIETARY_SWAPPED_FOR_PERMISSIVE_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_PM7_PROPRIETARY_SWAPPED_FOR_PERMISSIVE_BLOCKS)
        self.assertNotIn("W A R N I N G S", output)

    def test_pm8_permissive_swapped_for_proprietary_blocks(self):
        """
        Swap direction 2 -- permissive OSS license deleted, proprietary marking
        added in its place. BUG-3 (fixed): this used to report nothing at all.

        Rule #3 ("a solitary proprietary detection on the added side raises no
        issue") is evaluated before the deleted side is classified, and used to
        ignore the deleted side entirely -- swallowing the license change that
        the same deletion reports without the proprietary replacement, per
        test_pm8_control_permissive_deleted_alone_blocks. The skip now also
        requires that the deleted side gives up no license of its own, so
        relicensing third-party code as proprietary is reported as the license
        change COMPLIANCE.md scenario 3 rates HIGH impact.
        """
        output, code = self.run_main(
            patches.ADDITION_AND_DELETION,
            {"0_added.txt": PROPRIETARY_LICENSE, "0_deleted.txt": "MIT"},
            mode="proprietary",
        )
        self.assertEqual(code, EXPECTED_PM8_PERMISSIVE_SWAPPED_FOR_PROPRIETARY_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_PM8_PERMISSIVE_SWAPPED_FOR_PROPRIETARY_BLOCKS)

    def test_pm8_control_permissive_deleted_alone_blocks(self):
        """
        Control for BUG-3: the identical MIT deletion, with no proprietary
        marking added back, blocks. Isolates the added-side proprietary
        detection as what used to make test_pm8 report nothing.
        """
        _, code = self.run_main(
            patches.ADDITION_AND_DELETION, {"0_deleted.txt": "MIT"}, mode="proprietary"
        )
        self.assertEqual(code, 1)

    def test_pm9_marker_stripped_from_compound_deleted_expression_blocks(self):
        """
        BUG-3, compound form: the deleted side carries the proprietary marker
        *and* a real license, and only the marker survives. Since the marker is
        on both sides this is not a proprietary removal, so the block has to
        come from the deleted MIT -- which requires the added-side skip to
        weigh the deleted side component-wise rather than whole-string.
        """
        output, code = self.run_main(
            patches.ADDITION_AND_DELETION,
            {"0_added.txt": PROPRIETARY_LICENSE, "0_deleted.txt": f"MIT AND {PROPRIETARY_LICENSE}"},
            mode="proprietary",
        )
        self.assertEqual(code, EXPECTED_PM9_MARKER_STRIPPED_FROM_COMPOUND_BLOCKS_CODE)
        self.assertEqual(output, EXPECTED_PM9_MARKER_STRIPPED_FROM_COMPOUND_BLOCKS)

    def test_pm10_proprietary_marking_on_both_sides_is_silent(self):
        """
        The BUG-3 fix must not make reformatting noisy: the marker appearing on
        both sides of the diff (e.g. a rewrapped internal header) gives up no
        license, so it stays silent rather than reading as a license change.
        """
        output, code = self.run_main(
            patches.ADDITION_AND_DELETION,
            {"0_added.txt": PROPRIETARY_LICENSE, "0_deleted.txt": PROPRIETARY_LICENSE},
            mode="proprietary",
        )
        self.assertEqual(code, EXPECTED_PM10_PROPRIETARY_MARKING_REFORMATTED_SILENT_CODE)
        self.assertEqual(output, EXPECTED_PM10_PROPRIETARY_MARKING_REFORMATTED_SILENT)


class TestBug2ExitCodeTruncation(RegressionSnapshotTestCase):
    """
    BUG-2 (fixed): sys.exit(len(flagged_files)) used to hand the OS a POSIX
    exit status, which is truncated to 8 bits -- 256, 512, ... all became 0
    (a passing build). main() now exits 1 for any blocking issue regardless
    of file count. Deliberately not asserted as a full literal snapshot: the
    report text for 256 files is enormous and each file's block is identical
    except for its path, so the value-add of pinning it byte-for-byte is low
    next to the cost of a 20KB string literal. Structural assertions (exit
    code, section header, per-file block count) capture the same regression
    risk.
    """

    def test_256_flagged_files_exits_nonzero(self):
        """
        256 distinct blocking issues -> sys.exit(1), regardless of the
        flagged-file count, so the OS-level exit status is never masked to 0.
        """
        file_count = 256
        diff_parts = []
        detections = {}
        for idx in range(file_count):
            diff_parts.append(f"""diff --git a/src/file_{idx}.c b/src/file_{idx}.c
index 1234567..89abcde 100644
--- a/src/file_{idx}.c
+++ b/src/file_{idx}.c
@@ -1,1 +1,2 @@
 int f(void) {{
+    /* gpl text {idx} */
""")
            detections[f"{idx}_added.txt"] = "GPL-2.0-only"

        output, code = self.run_main("".join(diff_parts), detections)

        self.assertEqual(code, 1)
        self.assertIn("B L O C K I N G   E R R O R S", output)
        self.assertEqual(output.count("F I L E:"), file_count)
        for idx in range(file_count):
            self.assertIn(f"src/file_{idx}.c", output)


if __name__ == "__main__":
    unittest.main()
