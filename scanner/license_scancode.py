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
from scanner.patch import Patch

warnings.filterwarnings("ignore", message="Libmagic magic database not found")

# Canonical permissive-license list, independent of any repo's own detected
# license. In proprietary mode, permissive-OSS additions are judged against
# this list rather than self.permissive_licenses (which is derived from the
# scanning repo's own license and is not a meaningful baseline for a repo
# that correctly has no LICENSE file -- see LicenseChecker.run()).
PERMISSIVE_LICENSES = [
    "BSD-3-Clause",
    "MIT",
    "Apache-1.0",
    "Apache-1.1",
    "Apache-2.0",
    "BSD-3-Clause-Clear",
    "FreeBSD-DOC",
    "Zlib",
    "BSD-1-Clause",
    "BSD-2-Clause",
    "BSD-2-Clause-first-lines",
    "BSD-2-Clause-Views",
    "BSD-3-Clause-Sun",
    "BSD-4-Clause-Shortened",
    "BSD-3-Clause-Attribution",
    "BSD-4-Clause",
    "ISC",
    "CC0-1.0",
    "ICU",
    "LicenseRef-scancode-unicode",
    "Apache-2.0 WITH LLVM-exception",
    "Apache-2.0 WITH LLVM-exception AND Apache-2.0 AND LLVM-exception",
]

# What scancode reports for a Qualcomm-style proprietary rights statement.
PROPRIETARY_LICENSE = "LicenseRef-scancode-proprietary-license"


def split_license_components(expression: str) -> list:
    """
    Split an SPDX expression into its individual license components.

    Used for component-level checks that a whole-expression evaluation would
    miss -- e.g. spotting the proprietary marker inside
    "LicenseRef-scancode-proprietary-license AND GPL-2.0-only".

    Args:
        expression: An SPDX license expression, possibly compound.

    Returns:
        List of individual license identifiers, parentheses stripped.
    """
    if not expression:
        return []
    components = []
    for part in expression.replace("(", "").replace(")", "").split(" AND "):
        for lic in part.split(" OR "):
            lic = lic.strip()
            if lic:
                components.append(lic)
    return components


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

    # TODO: exceeds team max-complexity=10, branch count, and nesting depth
    # (SPDX expression evaluation covers AND/OR grouping plus GPL "-or-later"
    # compatibility; revisit extraction after proprietary mode lands, which
    # adds a canonical-list evaluation path).
    def is_license_permissive(self, scancode_license: str) -> bool:  # noqa: C901
        # pylint: disable=too-many-branches,too-many-nested-blocks
        """
        Check if a license is permissive by evaluating SPDX license expressions.

        Special handling for dual-license scenarios:
        - If expression starts with (X OR Y), we check if at least one option is permissive
        - If the same licenses appear later with AND, we ignore them (they're from comments)

        For OR expressions: At least one option must be permissive
        For AND expressions: All components must be permissive

        Special GPL compatibility handling:
        - If project has GPL-X.Y-or-later, files with GPL-X.Y-only or
          GPL-X.Y-or-later are compatible

        Args:
            scancode_license (str): The SPDX license expression to check.

        Returns:
            bool: True if the license expression is permissive, False otherwise.
        """
        expression = scancode_license.strip()

        # Check if this is a dual-license pattern: starts with (X OR Y) AND ...
        # In this case, if the OR part has a permissive option, we accept it
        if expression.startswith("(") and " OR " in expression.split(")")[0]:
            # Extract the OR part
            or_part = expression.split(")")[0] + ")"
            or_part_clean = or_part.strip("()")
            or_licenses = [lic.strip() for lic in or_part_clean.split(" OR ")]

            # Check if at least one license in the OR is permissive
            for lic in or_licenses:
                if lic in self.permissive_licenses:
                    return True

            return False

        # Standard evaluation: split by AND first to get AND-groups
        and_groups = [group.strip() for group in expression.split(" AND ")]

        # For each AND group, check if it's permissive
        for and_group in and_groups:
            # Check if this group contains OR
            if " OR " in and_group:
                # Remove parentheses
                and_group = and_group.strip("()")
                # Split by OR - at least one must be permissive
                or_licenses = [lic.strip() for lic in and_group.split(" OR ")]

                # Check if at least one license in the OR group is permissive
                has_permissive = False
                for lic in or_licenses:
                    if lic in self.permissive_licenses:
                        has_permissive = True
                        break

                if not has_permissive:
                    return False
            else:
                # Single license in this AND group - must be permissive
                lic = and_group.strip("()")

                # Check GPL "or-later" compatibility
                # If the file has GPL-X.Y-only or GPL-X.Y-or-later, and the
                # project allows GPL-X.Y-or-later, it's compatible
                if lic not in self.permissive_licenses:
                    # Check if this is a GPL license compatibility case
                    is_compatible = False
                    for allowed_lic in self.permissive_licenses:
                        if "-or-later" in allowed_lic:
                            # Extract base license (e.g., "GPL-2.0" from "GPL-2.0-or-later")
                            base_license = allowed_lic.replace("-or-later", "")
                            # Check if file license is compatible
                            if lic in (allowed_lic, f"{base_license}-only", base_license):
                                is_compatible = True
                                break

                    if not is_compatible:
                        return False

        return True

    # TODO: exceeds team max-complexity=10 and local-variable count (batches
    # added/deleted line groups across all changes into one scancode
    # invocation; revisit extraction if proprietary mode needs to change how
    # content is batched).
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

    # TODO: exceeds team max-complexity=10 (rule branches mirror the blocking
    # scenarios documented in COMPLIANCE.md; proprietary mode adds further
    # branches here per that same documentation).
    def run(self) -> tuple:  # noqa: C901
        # pylint: disable=too-many-branches
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
          of the blocking error it is in opensource mode.
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

            if proprietary and not proprietary_removed and added_licenses == PROPRIETARY_LICENSE:
                # Expected for internal Qualcomm headers; not an issue at all.
                continue

            issues = []
            if change["change_type"] == "MODIFIED" or change["change_type"] == "ADDED":
                # In proprietary mode a retained proprietary marker is expected, not a
                # compatibility problem, so permissiveness is judged on the rest of the
                # expression. Otherwise "MIT AND <proprietary>" would fail the AND rule
                # (every component must be permissive) and block a change that is really
                # just permissive code added to a still-marked internal file.
                added_for_permissiveness = (
                    self._without_proprietary_marker(added_licenses)
                    if proprietary
                    else added_licenses
                )
                added_is_permissive = bool(added_for_permissiveness) and self.is_license_permissive(
                    added_for_permissiveness
                )

                if proprietary_removed:
                    issues.append(self._proprietary_removed_message(deleted_licenses))
                # Check if licenses changed
                elif added_licenses and deleted_licenses and added_licenses != deleted_licenses:
                    # Only flag if the new license is NOT permissive
                    # This allows dual-license scenarios like "BSD-3-Clause OR GPL-2.0-only"
                    # where at least one option is permissive
                    if not added_is_permissive:
                        issues.append(
                            f"License deleted: {deleted_licenses} and license added: {added_licenses}"  # noqa: E501
                        )
                elif added_licenses and not added_is_permissive:
                    # New license added that is not permissive
                    issues.append(f"Incompatible license added: {added_licenses}")
                elif deleted_licenses and not added_licenses:
                    # License was removed without replacement
                    issues.append(f"License deleted: {deleted_licenses}")

                # A permissive license newly appeared (as opposed to an unchanged license
                # showing identically on both sides of the diff, e.g. from reformatting).
                # In proprietary mode this warns about the NOTICE attribution obligation.
                # Skipped when a proprietary marking was removed -- that is an error above,
                # and warning about it too would muddy the report.
                license_is_new_or_changed = added_licenses and added_licenses != deleted_licenses
                if (
                    proprietary
                    and not proprietary_removed
                    and license_is_new_or_changed
                    and added_is_permissive
                ):
                    warning_files.setdefault(change["path_name"], []).append(
                        self._notice_reminder(added_licenses)
                    )

                if issues:
                    flagged_files[change["path_name"]] = issues
            if change["change_type"] == "ADDED":
                if not added_licenses and self.is_source_file(change["path_name"]):
                    if not (
                        proprietary
                        and has_internal_copyright(change["content"], self.proprietary_entities)
                    ):
                        flagged_files.setdefault(change["path_name"], []).append(
                            self._no_license_message(change["path_name"], proprietary)
                        )
        return flagged_files, warning_files

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
