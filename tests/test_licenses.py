"""
Tests for scanner.licenses: SPDX expression parsing, classification
predicates, and the canonical license lists.
"""

import unittest

from scanner.licenses import (
    PERMISSIVE_LICENSES,
    PROPRIETARY_LICENSE,
    is_copyleft,
    is_license_allowed,
    is_permissive,
    is_proprietary_marker,
    is_uncertain_expression,
    split_license_components,
)

COPYLEFT = [
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
]


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


class TestIsLicenseAllowed(unittest.TestCase):
    """The SPDX expression evaluator."""

    def test_single_permissive_license(self):
        """A lone permissive identifier is allowed."""
        self.assertTrue(is_license_allowed("MIT", PERMISSIVE_LICENSES))

    def test_single_copyleft_license(self):
        """A lone copyleft identifier is not allowed under a permissive list."""
        self.assertFalse(is_license_allowed("GPL-2.0-only", PERMISSIVE_LICENSES))

    def test_whitespace_is_stripped(self):
        """Surrounding whitespace does not affect evaluation."""
        self.assertTrue(is_license_allowed("  MIT  ", PERMISSIVE_LICENSES))

    def test_and_requires_all_allowed(self):
        """Every component of an AND expression must be allowed."""
        self.assertTrue(is_license_allowed("MIT AND Apache-2.0", PERMISSIVE_LICENSES))
        self.assertFalse(is_license_allowed("MIT AND GPL-2.0-only", PERMISSIVE_LICENSES))

    def test_or_requires_at_least_one_allowed(self):
        """An OR group passes when any single option is allowed."""
        self.assertTrue(is_license_allowed("(MIT OR GPL-2.0-only)", PERMISSIVE_LICENSES))
        self.assertFalse(is_license_allowed("(GPL-2.0-only OR GPL-3.0-only)", PERMISSIVE_LICENSES))

    def test_non_leading_or_group_is_evaluated_by_the_general_loop(self):
        """
        An OR group that is not the leading term takes the general AND-groups
        loop's own OR-handling, not the leading-OR-group special case (see
        test_leading_or_group_short_circuits) -- a currently-reachable but
        previously untested code path.
        """
        self.assertTrue(
            is_license_allowed("MIT AND (GPL-2.0-only OR BSD-3-Clause)", PERMISSIVE_LICENSES)
        )
        self.assertFalse(
            is_license_allowed("MIT AND (GPL-2.0-only OR GPL-3.0-only)", PERMISSIVE_LICENSES)
        )

    def test_leading_or_group_does_not_exempt_the_rest_of_the_expression(self):
        """
        BUG-3 (fixed): a leading '(X OR Y) AND Z' dual-license expression is
        now evaluated uniformly, so a trailing incompatible component still
        fails the check -- it is no longer decided solely by the leading OR
        group, treating everything after it as comment noise to ignore.
        """
        self.assertFalse(
            is_license_allowed("(MIT OR GPL-2.0-only) AND GPL-3.0-only", PERMISSIVE_LICENSES)
        )
        self.assertTrue(
            is_license_allowed("(MIT OR GPL-2.0-only) AND Apache-2.0", PERMISSIVE_LICENSES)
        )

    def test_unknown_license_is_not_allowed(self):
        """An identifier absent from the allowed list is not allowed."""
        self.assertFalse(is_license_allowed("LicenseRef-scancode-unknown", PERMISSIVE_LICENSES))


class TestGplOrLaterCompatibility(unittest.TestCase):
    """GPL '-or-later' backward compatibility against a copyleft project."""

    def test_or_later_accepts_only_variant(self):
        """A project allowing GPL-2.0-or-later also accepts GPL-2.0-only."""
        self.assertTrue(is_license_allowed("GPL-2.0-only", COPYLEFT))

    def test_or_later_accepts_bare_base_license(self):
        """The bare base identifier is accepted too."""
        self.assertTrue(is_license_allowed("GPL-2.0", ["GPL-2.0-or-later"]))

    def test_permissive_project_rejects_gpl(self):
        """A permissive project does not accept GPL via this path."""
        self.assertFalse(is_license_allowed("GPL-2.0-only", PERMISSIVE_LICENSES))


class TestIsPermissive(unittest.TestCase):
    """
    is_permissive is the canonical check against PERMISSIVE_LICENSES,
    independent of whatever allowed list a caller constructed with -- see
    BUG-4 in CODE_REVIEW.md.
    """

    def test_permissive_license_is_permissive(self):
        """A canonical permissive identifier is permissive."""
        self.assertTrue(is_permissive("MIT"))

    def test_copyleft_license_is_not_permissive(self):
        """A copyleft identifier is never permissive, regardless of caller context."""
        self.assertFalse(is_permissive("GPL-2.0-only"))

    def test_unrelated_allowed_list_does_not_affect_result(self):
        """
        Unlike is_license_allowed, is_permissive ignores any repo-specific
        allowed list -- GPL-2.0-only is not permissive even for a repo whose
        own allowed list is entirely copyleft.
        """
        self.assertFalse(is_permissive("GPL-2.0-only"))
        self.assertTrue(is_license_allowed("GPL-2.0-only", COPYLEFT))


class TestIsCopyleft(unittest.TestCase):
    """Plain membership check against COPYLEFT_LICENSES."""

    def test_known_copyleft_license(self):
        """A listed copyleft identifier is recognized."""
        self.assertTrue(is_copyleft("GPL-2.0-only"))

    def test_permissive_license_is_not_copyleft(self):
        """A permissive identifier is not copyleft."""
        self.assertFalse(is_copyleft("MIT"))

    def test_compound_expression_is_not_a_member(self):
        """This is a plain list membership check, not expression evaluation."""
        self.assertFalse(is_copyleft("GPL-2.0-only AND MIT"))


class TestIsProprietaryMarker(unittest.TestCase):
    """Single-identifier check for the proprietary marker."""

    def test_marker_matches(self):
        """The exact marker string matches."""
        self.assertTrue(is_proprietary_marker(PROPRIETARY_LICENSE))

    def test_other_license_does_not_match(self):
        """Any other identifier does not match."""
        self.assertFalse(is_proprietary_marker("MIT"))

    def test_compound_expression_does_not_match(self):
        """A compound expression containing the marker is not itself the marker."""
        self.assertFalse(is_proprietary_marker(f"MIT AND {PROPRIETARY_LICENSE}"))


class TestIsUncertainExpression(unittest.TestCase):
    """
    Classification of an SPDX expression as uncertain (all components
    unrecognized LicenseRef-scancode-* identifiers) vs. a real verdict.
    """

    def test_empty_expression_is_not_uncertain(self):
        """An empty/unparseable expression is not uncertain."""
        self.assertFalse(is_uncertain_expression(""))

    def test_known_license_is_not_uncertain(self):
        """A recognized SPDX identifier is never uncertain."""
        self.assertFalse(is_uncertain_expression("MIT"))

    def test_lone_unknown_reference_is_uncertain(self):
        """A solitary unrecognized LicenseRef-scancode-* is uncertain."""
        self.assertTrue(is_uncertain_expression("LicenseRef-scancode-unknown-license-reference"))

    def test_mixed_unknown_and_known_is_not_uncertain(self):
        """Any recognized component forces a real verdict, not uncertain."""
        self.assertFalse(
            is_uncertain_expression(
                "GPL-2.0-only AND LicenseRef-scancode-unknown-license-reference"
            )
        )

    def test_all_unknown_components_is_uncertain(self):
        """An expression made only of uncertain references is uncertain."""
        self.assertTrue(
            is_uncertain_expression(
                "LicenseRef-scancode-unknown-license-reference AND "
                "LicenseRef-scancode-warranty-disclaimer"
            )
        )

    def test_solitary_proprietary_marker_is_not_uncertain(self):
        """
        The one exception: a lone proprietary marker is always a real
        (blocking) verdict, never downgraded to uncertain.
        """
        self.assertFalse(is_uncertain_expression(PROPRIETARY_LICENSE))

    def test_proprietary_marker_mixed_with_unknown_is_uncertain(self):
        """Mixed with another uncertain reference, the marker no longer exempts it."""
        self.assertTrue(
            is_uncertain_expression(
                f"{PROPRIETARY_LICENSE} AND LicenseRef-scancode-unknown-license-reference"
            )
        )


if __name__ == "__main__":
    unittest.main()
