"""
Single home for SPDX license-expression parsing, classification, and the
canonical license lists. Consolidates knowledge that used to be split across
main.py (COPYLEFT_LICENSES, a hand-rolled AND/OR splitter) and
license_scancode.py (PERMISSIVE_LICENSES, PROPRIETARY_LICENSE,
split_license_components, is_uncertain_expression) so severity logic and
list membership live in one place.
"""

# Canonical permissive-license list, independent of any repo's own detected
# license. In proprietary mode, permissive-OSS additions are judged against
# this list rather than a checker's own self.permissive_licenses (which is
# derived from the scanning repo's own license and is not a meaningful
# baseline for a repo that correctly has no LICENSE file).
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

# Copyleft licenses recognized when resolving a repo's own allowed list.
COPYLEFT_LICENSES = [
    "GPL-1.0-only",
    "GPL-1.0-or-later",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0",
    "GPL-3.0-or-later",
    "AGPL-3.0",
    "LGPL-3.0",
    "GPL-2.0",
    "GPL-2.0+",
    "GPL-2.0-only WITH Linux-syscall-note",
    "AGPL-1.0-only",
    "AGPL-1.0-or-later",
    "LicenseRef-scancode-agpl-2.0",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
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


def is_uncertain_expression(expression: str) -> bool:
    """
    Check whether every component of an SPDX expression is an uncertain
    (unrecognized) license, making the expression a warning rather than a
    blocking error.

    A component is uncertain when it is a "LicenseRef-scancode-*" identifier
    that isn't in PERMISSIVE_LICENSES -- i.e. scancode couldn't map it to a
    known license. A solitary PROPRIETARY_LICENSE is the one exception: it is
    always a blocking error on its own (see COMPLIANCE.md scenario 7), so it
    is never treated as uncertain here.

    Args:
        expression: An SPDX license expression, possibly compound.

    Returns:
        bool: True if every component is uncertain, False otherwise
            (including for an empty/unparseable expression).
    """
    licenses = split_license_components(expression)
    if not licenses:
        return False
    if len(licenses) == 1 and licenses[0] == PROPRIETARY_LICENSE:
        return False
    return all(
        lic.startswith("LicenseRef-scancode-") and lic not in PERMISSIVE_LICENSES
        for lic in licenses
    )


def is_proprietary_marker(license_id: str) -> bool:
    """
    Check whether a single license identifier is the proprietary marker.

    Args:
        license_id: A single license identifier (not a compound expression).

    Returns:
        bool: True if license_id is exactly the proprietary marker.
    """
    return license_id == PROPRIETARY_LICENSE


def is_copyleft(license_str: str) -> bool:
    """
    Check whether a license string is one of the recognized copyleft licenses.

    A plain membership check, matching how a repo's own top-level detected
    license is classified in main.py -- distinct from is_license_allowed,
    which evaluates a possibly-compound SPDX expression against an allowed
    list.

    Args:
        license_str: A single license identifier.

    Returns:
        bool: True if license_str is in COPYLEFT_LICENSES.
    """
    return license_str in COPYLEFT_LICENSES


# Exceeds team max-complexity=10, branch count, and nesting depth: SPDX
# expression evaluation covers AND/OR grouping plus GPL "-or-later"
# compatibility. Simplifying this further is blocked on the open question in
# #6 (the leading-OR-group short-circuit this evaluates around) -- revisit
# once that's resolved, not on a generic "after proprietary mode" timeline.
def is_license_allowed(expression: str, allowed_licenses: list) -> bool:  # noqa: C901
    # pylint: disable=too-many-branches,too-many-nested-blocks
    """
    Check whether an SPDX license expression is allowed under allowed_licenses.

    Special handling for dual-license scenarios:
    - If expression starts with (X OR Y), we check if at least one option is allowed
    - If the same licenses appear later with AND, we ignore them (they're from comments)

    For OR expressions: at least one option must be allowed.
    For AND expressions: all components must be allowed.

    Special GPL compatibility handling:
    - If allowed_licenses contains GPL-X.Y-or-later, GPL-X.Y-only and
      GPL-X.Y-or-later are both accepted.

    Args:
        expression: The SPDX license expression to check.
        allowed_licenses: The list an expression's components are checked
            against -- either a repo's own derived allowed list, or the
            canonical PERMISSIVE_LICENSES (see is_permissive).

    Returns:
        bool: True if the license expression is allowed, False otherwise.
    """
    expression = expression.strip()

    # Check if this is a dual-license pattern: starts with (X OR Y) AND ...
    # In this case, if the OR part has an allowed option, we accept it
    if expression.startswith("(") and " OR " in expression.split(")")[0]:
        or_part = expression.split(")")[0] + ")"
        or_part_clean = or_part.strip("()")
        or_licenses = [lic.strip() for lic in or_part_clean.split(" OR ")]

        for lic in or_licenses:
            if lic in allowed_licenses:
                return True

        return False

    # Standard evaluation: split by AND first to get AND-groups
    and_groups = [group.strip() for group in expression.split(" AND ")]

    for and_group in and_groups:
        if " OR " in and_group:
            or_group = and_group.strip("()")
            or_licenses = [lic.strip() for lic in or_group.split(" OR ")]

            if not any(lic in allowed_licenses for lic in or_licenses):
                return False
        else:
            lic = and_group.strip("()")

            if lic not in allowed_licenses:
                # Check GPL "or-later" compatibility: if the project allows
                # GPL-X.Y-or-later, files with GPL-X.Y-only or GPL-X.Y-or-later
                # are compatible.
                is_compatible = False
                for allowed_lic in allowed_licenses:
                    if "-or-later" in allowed_lic:
                        base_license = allowed_lic.replace("-or-later", "")
                        if lic in (allowed_lic, f"{base_license}-only", base_license):
                            is_compatible = True
                            break

                if not is_compatible:
                    return False

    return True


def is_permissive(expression: str) -> bool:
    """
    Check whether an SPDX license expression is allowed under the canonical
    permissive list, independent of whatever allowed list a caller happens
    to be using for its own repo.

    Args:
        expression: The SPDX license expression to check.

    Returns:
        bool: True if the expression is allowed under PERMISSIVE_LICENSES.
    """
    return is_license_allowed(expression, PERMISSIVE_LICENSES)
