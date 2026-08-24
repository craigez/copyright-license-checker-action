"""
Module to check for licenses in a patch file using scancode.
"""

import json
import tempfile
import subprocess
import warnings
import os
from pathlib import Path

from scanner.copyright_checker import DEFAULT_INTERNAL_ENTITIES, has_internal_copyright
from scanner.licenses import (
    PROPRIETARY_LICENSE,
    is_license_allowed,
    is_permissive,
    is_uncertain_expression,
    split_license_components,
)
from scanner.patch import Patch

warnings.filterwarnings("ignore", message="Libmagic magic database not found")


def _route_license_message(
    message: str, expression: str, issues: list, warning_messages: list
) -> None:
    """Append message to warning_messages if expression is uncertain, otherwise to issues."""
    target = warning_messages if is_uncertain_expression(expression) else issues
    target.append(message)


class LicenseChecker:
    """
    Class to check for licenses in a patch file.
    """

    def __init__(
        self,
        patch: Patch,
        repo: str,
        permissive_licenses: list,
        mode: str = "opensource",
        proprietary_entities: list | None = None,
    ) -> None:
        """
        Initialize the LicenseChecker object.

        Args:
            patch (Patch): The patch file to check.
            repo (str): The repository name.
            permissive_licenses (list): A list of permissive licenses.
            mode (str): "opensource" (default) or "proprietary". In
                "opensource" mode, run() behavior is unchanged from before
                mode support existed.
            proprietary_entities (list): Copyright-holder substrings treated
                as internal authorship in proprietary mode. Defaults to
                scanner.copyright_checker.DEFAULT_INTERNAL_ENTITIES when None.
        """
        self.patch = patch
        self.repo = repo
        self.permissive_licenses = permissive_licenses
        self.mode = mode
        self.proprietary_entities = (
            proprietary_entities if proprietary_entities is not None else DEFAULT_INTERNAL_ENTITIES
        )

    # Exceeds team max-complexity=10 and local-variable count: batches
    # added/deleted line groups across all changes into one scancode
    # invocation. Proprietary mode landed without needing to change this
    # batching (see PERF-3 in CODE_REVIEW.md) -- kept as-is; splitting it
    # would risk losing the single-subprocess-call guarantee this exists for.
    def detect_licenses_batch(self, changes: list) -> dict:  # noqa: C901
        # pylint: disable=too-many-locals
        """
        Detect licenses for multiple changes in a single scancode run.
        Args:
            changes (list): List of changes to check.
        Returns:
            dict: Dictionary mapping (change_index, content_type) -> licenses.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_map = {}

            for idx, change in enumerate(changes):
                content = change["content"]
                # Check if content is None
                if not content:
                    continue

                added_lines = []
                deleted_lines = []
                # Separate added and deleted lines
                for line in content.split("\n"):
                    if line.startswith("+"):
                        added_lines.append(line[1:])
                    elif line.startswith("-"):
                        deleted_lines.append(line[1:])

                # Join added and deleted lines as-is
                if added_lines:
                    added_file = f"{idx}_added.txt"
                    Path(tmpdir, added_file).write_text("\n".join(added_lines), encoding="utf-8")
                    file_map[added_file] = (idx, "added")

                if deleted_lines:
                    deleted_file = f"{idx}_deleted.txt"
                    Path(tmpdir, deleted_file).write_text(
                        "\n".join(deleted_lines), encoding="utf-8"
                    )
                    file_map[deleted_file] = (idx, "deleted")

            if not file_map:
                return {}

            output_file = os.path.join(tmpdir, "scancode_results.json")
            subprocess.run(
                [
                    "scancode",
                    "--license",
                    "--strip-root",
                    "--quiet",
                    "--json-pp",
                    output_file,
                    tmpdir,
                ],
                check=True,
            )

            with open(output_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            results = {}
            for file_result in data.get("files", []):
                if file_result["type"] != "file":
                    continue

                filename = os.path.basename(file_result["path"])
                if filename not in file_map:
                    continue

                licenses = ""
                if len(file_result.get("license_detections", [])):
                    licenses = file_result["license_detections"][0]["license_expression_spdx"]

                change_idx, content_type = file_map[filename]
                results[(change_idx, content_type)] = licenses

            return results

    def is_source_file(self, file_name: str) -> bool:
        """
        Check if a file is a source file.

        Args:
            file_name (str): The file name.

        Returns:
            bool: True if the file is a source file, False otherwise.
        """
        # Define common source file extensions
        source_file_extensions = [
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".java",
            ".py",
            ".js",
            ".ts",
            ".rb",
            ".go",
            ".swift",
            ".kt",
            ".kts",
            ".sh",
        ]

        # Check if the file extension is in the list of source file extensions
        for ext in source_file_extensions:
            if file_name.endswith(ext):
                return True
        return False

    def run(self) -> tuple:
        """
        Run the license checker.

        In "opensource" mode, behavior is unchanged from before mode support
        existed. In "proprietary" mode -- note that main.py passes the
        canonical PERMISSIVE_LICENSES as self.permissive_licenses in this
        mode, since a proprietary repo's own (absent) LICENSE file is not a
        meaningful permissiveness baseline:

        - Removing a proprietary marking is a blocking error, whatever
          replaces it. This takes precedence over the permissive-addition
          warning below: a diff that deletes the proprietary statement and
          adds a permissive license in its place is still a removal of
          proprietary marking, so it blocks. Removal counts even when the
          marker is one component of a compound deleted expression.
        - Adding a permissive OSS license to a file that was not carrying a
          proprietary marking being removed (i.e. an unmarked file, or a file
          keeping its proprietary marking) is a warning reminding the author
          to update the repo's NOTICE file. Copyleft/unknown licenses are
          unaffected and still block.
        - A solitary proprietary-license detection on the added side is
          expected for internal headers and raises no issue at all, instead
          of the blocking error it is in opensource mode -- but only when the
          change gives up no license of its own. Deleting a real license and
          marking the file proprietary in its place is a relicensing of
          third-party code and is still reported.
        - A new source file with no detected license is not blocked if it
          carries a copyright naming one of self.proprietary_entities (the
          normal case for internal files). Otherwise it is still blocked,
          with a message distinguishing "third-party, route to scan
          team/legal" from "ours, needs a copyright marking" rather than the
          generic opensource-mode message.

        Returns:
            tuple: A (flagged_files, warning_files) pair. flagged_files maps
                path -> list of blocking issue strings; warning_files maps
                path -> list of non-blocking issue strings.
        """
        source_files = [change for change in self.patch.changes if change["file_type"] == "source"]

        flagged_files = {}
        warning_files = {}
        if not source_files:
            return flagged_files, warning_files

        license_results = self.detect_licenses_batch(source_files)
        proprietary = self.mode == "proprietary"

        for idx, change in enumerate(source_files):
            added_licenses = license_results.get((idx, "added"), "")
            deleted_licenses = license_results.get((idx, "deleted"), "")

            proprietary_removed = proprietary and self._proprietary_marking_removed(
                added_licenses, deleted_licenses
            )

            if proprietary and self._is_expected_internal_marking(added_licenses, deleted_licenses):
                # Expected for internal Qualcomm headers; not an issue at all.
                continue

            if change["change_type"] in ("MODIFIED", "ADDED"):
                self._classify_license_change(
                    change,
                    {
                        "added": added_licenses,
                        "deleted": deleted_licenses,
                        "proprietary": proprietary,
                        "proprietary_removed": proprietary_removed,
                    },
                    flagged_files,
                    warning_files,
                )
            if change["change_type"] == "ADDED":
                no_license_message = self._check_new_file_license(
                    change, added_licenses, proprietary
                )
                if no_license_message:
                    flagged_files.setdefault(change["path_name"], []).append(no_license_message)
        return flagged_files, warning_files

    def _check_new_file_license(
        self, change: dict, added_licenses: str, proprietary: bool
    ) -> str | None:
        """
        Check a newly-added source file for a missing license.

        Args:
            change (dict): The ADDED change under consideration.
            added_licenses (str): SPDX expression detected on the added lines.
            proprietary (bool): Whether the checker is running in proprietary mode.

        Returns:
            str | None: A blocking message if the file has no detected
                license and (in proprietary mode) no internal copyright
                either; None if the file should raise no issue.
        """
        if added_licenses or not self.is_source_file(change["path_name"]):
            return None
        if proprietary and has_internal_copyright(change["content"], self.proprietary_entities):
            return None
        return self._no_license_message(change["path_name"], proprietary)

    def _classify_license_change(
        self, change: dict, license_info: dict, flagged_files: dict, warning_files: dict
    ) -> None:
        """
        Classify a MODIFIED/ADDED change's license issues into flagged_files/warning_files.

        In proprietary mode a retained proprietary marker is expected, not a
        compatibility problem, so permissiveness is judged on the rest of the
        expression. Otherwise "MIT AND <proprietary>" would fail the AND rule
        (every component must be permissive) and block a change that is really
        just permissive code added to a still-marked internal file.
        """
        added_licenses = license_info["added"]
        deleted_licenses = license_info["deleted"]
        proprietary = license_info["proprietary"]
        proprietary_removed = license_info["proprietary_removed"]

        added_for_permissiveness = (
            self._without_proprietary_marker(added_licenses) if proprietary else added_licenses
        )
        added_is_allowed = bool(added_for_permissiveness) and is_license_allowed(
            added_for_permissiveness, self.permissive_licenses
        )

        issues = []
        warnings_for_file = []
        if proprietary_removed:
            issues.append(self._proprietary_removed_message(deleted_licenses))
        elif proprietary and deleted_licenses and added_licenses == PROPRIETARY_LICENSE:
            # A real license replaced by a bare proprietary marking: the same
            # relicensing hazard as the generic "License deleted/added" message
            # below, but naming the marker specifically rather than reporting
            # it as though a different real license had been substituted.
            issues.append(self._relicensed_as_proprietary_message(deleted_licenses))
        # Check if licenses changed
        elif added_licenses and deleted_licenses and added_licenses != deleted_licenses:
            # Only flag if the new license is NOT allowed. This allows dual-license
            # scenarios like "BSD-3-Clause OR GPL-2.0-only" where at least one option
            # is allowed.
            if not added_is_allowed:
                message = f"License deleted: {deleted_licenses} and license added: {added_licenses}"  # noqa: E501
                _route_license_message(message, added_licenses, issues, warnings_for_file)
        elif added_licenses and not added_is_allowed:
            # New license added that is not allowed
            message = f"Incompatible license added: {added_licenses}"
            _route_license_message(message, added_licenses, issues, warnings_for_file)
        elif deleted_licenses and not added_licenses:
            # License was removed without replacement
            message = f"License deleted: {deleted_licenses}"
            _route_license_message(message, deleted_licenses, issues, warnings_for_file)

        # A permissive license newly appeared (as opposed to an unchanged license
        # showing identically on both sides of the diff, e.g. from reformatting).
        # In proprietary mode this warns about the NOTICE attribution obligation.
        # Skipped when a proprietary marking was removed -- that is an error above,
        # and warning about it too would muddy the report. Judged against the
        # canonical is_permissive() rather than added_is_allowed/
        # self.permissive_licenses: this is specifically "is this permissive
        # open-source code," not "is this allowed for the calling repo," and
        # must not depend on whatever list happened to be passed to the
        # constructor.
        license_is_new_or_changed = added_licenses and added_licenses != deleted_licenses
        if (
            proprietary
            and not proprietary_removed
            and license_is_new_or_changed
            and added_for_permissiveness
            and is_permissive(added_for_permissiveness)
        ):
            warning_files.setdefault(change["path_name"], []).append(
                self._notice_reminder(added_licenses)
            )

        if issues:
            flagged_files[change["path_name"]] = issues
        if warnings_for_file:
            warning_files.setdefault(change["path_name"], []).extend(warnings_for_file)

    @staticmethod
    def _without_proprietary_marker(expression: str) -> str:
        """
        Drop the proprietary marker from an SPDX expression.

        A retained proprietary marking is expected in proprietary mode, so it
        must not count against the "all AND components must be permissive"
        rule when judging whatever else the change added.

        Args:
            expression (str): An SPDX license expression, possibly compound.

        Returns:
            str: The expression's remaining components rejoined with " AND ",
                or "" if the proprietary marker was the only component.
        """
        remaining = [
            lic for lic in split_license_components(expression) if lic != PROPRIETARY_LICENSE
        ]
        return " AND ".join(remaining)

    @classmethod
    def _is_expected_internal_marking(cls, added_licenses: str, deleted_licenses: str) -> bool:
        """
        Check whether a change is no more than an internal marking appearing.

        True when the added side is a solitary proprietary marker *and* the
        deleted side gives up no license of its own -- the normal shape of a
        change that adds, or merely reformats, an internal Qualcomm header.
        That raises no issue at all in proprietary mode.

        The deleted-side condition is what keeps this from swallowing a
        relicensing: a diff that drops a real license (say MIT) and marks the
        file proprietary in its place is a license change on third-party code,
        and must still be reported rather than waved through as an expected
        internal header.

        Args:
            added_licenses (str): SPDX expression detected on added lines.
            deleted_licenses (str): SPDX expression detected on deleted lines.

        Returns:
            bool: True if the change is an expected internal marking.
        """
        if added_licenses != PROPRIETARY_LICENSE:
            return False
        return not cls._without_proprietary_marker(deleted_licenses)

    @staticmethod
    def _proprietary_marking_removed(added_licenses: str, deleted_licenses: str) -> bool:
        """
        Check whether a proprietary marking was removed by this change.

        Component-level so that removing the marker from a compound
        expression (e.g. "proprietary AND GPL-2.0-only") still counts.

        Args:
            added_licenses (str): SPDX expression detected on added lines.
            deleted_licenses (str): SPDX expression detected on deleted lines.

        Returns:
            bool: True if the proprietary marker appears among the deleted
                components but not among the added ones. A marker present on
                both sides is unchanged (e.g. a reformatted header), not a
                removal.
        """
        deleted_components = split_license_components(deleted_licenses)
        if PROPRIETARY_LICENSE not in deleted_components:
            return False
        return PROPRIETARY_LICENSE not in split_license_components(added_licenses)

    @staticmethod
    def _proprietary_removed_message(deleted_licenses: str) -> str:
        """
        Build the blocking message for a removed proprietary marking.

        Args:
            deleted_licenses (str): The deleted SPDX license expression.

        Returns:
            str: A blocking error message.
        """
        return (
            f"Proprietary license statement removed: {deleted_licenses} -- removing a "
            "proprietary rights statement requires review; restore it, or route the "
            "change to the scan team/legal if the file's status has genuinely changed."
        )

    @staticmethod
    def _relicensed_as_proprietary_message(deleted_licenses: str) -> str:
        """
        Build the blocking message for a real license replaced by a bare
        proprietary marking.

        Distinct from _proprietary_removed_message: here the proprietary
        marker is being *added*, not removed, but the deleted side still gave
        up a real license -- e.g. deleting an MIT header and marking the file
        proprietary in its place. Naming the marker directly is clearer than
        the generic license-change message, since "license added:
        LicenseRef-scancode-proprietary-license" reads as though some other
        real license had been substituted rather than a proprietary claim.

        Args:
            deleted_licenses (str): The deleted SPDX license expression.

        Returns:
            str: A blocking error message.
        """
        return (
            f"License deleted: {deleted_licenses} and license added: {PROPRIETARY_LICENSE} -- "
            "a permissive license's attribution terms are not extinguished by marking the "
            "file proprietary; restore the deleted license, or route the change to the scan "
            "team/legal if the file's licensing has genuinely changed."
        )

    @staticmethod
    def _notice_reminder(added_licenses: str) -> str:
        """
        Build the proprietary-mode warning for a permissive OSS addition.

        Args:
            added_licenses (str): The added SPDX license expression.

        Returns:
            str: A warning message reminding the author to update NOTICE.
        """
        return (
            f"Permissive open-source license added: {added_licenses} -- review that this "
            "third-party code is approved for inclusion, and update the repo's NOTICE file "
            "with the required attribution."
        )

    @staticmethod
    def _no_license_message(path_name: str, proprietary: bool) -> str:
        """
        Build the "no license detected on a new source file" message.

        Args:
            path_name (str): The path of the file with no detected license.
            proprietary (bool): Whether the checker is running in
                proprietary mode.

        Returns:
            str: In opensource mode, the original generic message. In
                proprietary mode, a message distinguishing the two real
                possibilities: unmarked third-party code (route to scan
                team/legal, do not add a Qualcomm copyright) versus
                unmarked Qualcomm-authored code (add the copyright marking).
        """
        if not proprietary:
            return f"No license added for source file: {path_name}"
        return (
            f"No license or internal copyright found for source file: {path_name} -- "
            "if this is third-party code, do NOT add a Qualcomm copyright; route it to "
            "the scan team/legal for review. If this is Qualcomm-authored code, add the "
            "appropriate copyright marking."
        )
