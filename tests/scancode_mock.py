"""
Shared scancode subprocess.run mock and temp-cwd test isolation, used by
test_license_scancode.py, test_main.py, and test_regression_snapshot.py.
Consolidated here so the scancode JSON report shape and the tempdir/chdir
isolation idiom are each defined once (DUP-3-adjacent finding from TOOL-2 in
CODE_REVIEW.md: pylint's duplicate-code flagged these as new duplication
that emerged after the original two accepted spans were documented).
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch as mock_patch


def scancode_mock_patcher(detections: dict):
    """
    Build a mock.patch for scanner.license_scancode.subprocess.run that writes
    a scancode-shaped JSON report keyed by the filenames detect_licenses_batch scans.

    Args:
        detections: Maps scanned filename (e.g. '0_added.txt') to either an
            SPDX expression string, or None for 'no license detected'.

    Returns:
        An unittest.mock.patch context manager for
        scanner.license_scancode.subprocess.run.
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

    return mock_patch("scanner.license_scancode.subprocess.run", side_effect=fake_run)


class TempCwdMixin:
    """Runs each test inside a scratch working directory, isolated from any real files."""

    def setUp(self):
        """Change into a temporary directory for the test's lifetime."""
        # pylint: disable=consider-using-with
        # A `with` block can't span setUp/tearDown; addCleanup is the correct
        # unittest idiom for scoping a TemporaryDirectory to the test lifetime.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        original_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, original_cwd)
