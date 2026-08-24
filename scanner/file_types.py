"""
File-type extension lists shared across the scanner.

Single source of truth for the two lists documented in README.md and
COMPLIANCE.md -- Patch's exclusions and LicenseChecker's source-file
inclusions -- so the docs and the code cannot silently drift apart.
tests/test_file_types.py ties the documented lists to these tuples.
"""

# Files skipped entirely by Patch, before any license/copyright check runs.
EXCLUDED_EXTENSIONS = (".patch", ".bb", ".md", ".json", ".yml")

# Extensions LicenseChecker treats as source code requiring a license.
SOURCE_EXTENSIONS = (
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
)
