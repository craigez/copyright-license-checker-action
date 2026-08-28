# Compliance Documentation

## Overview

This GitHub Action enforces copyright and license compliance for code changes in pull requests. It analyzes the diff/patch to ensure that all modifications adhere to the repository's licensing policies and copyright requirements.

**Action Repository**: https://github.com/qualcomm/copyright-license-checker-action

> **Two modes.** This document describes `mode: opensource` (the default) unless a section says otherwise. If you are checking an internally-developed proprietary codebase, set `mode: proprietary` and read [Proprietary Mode](#proprietary-mode) alongside this — most rules are identical, but a few differ.

## Build Blocking Scenarios

The following scenarios will **BLOCK** your build and require remediation before the PR can be merged:

### 1. Incompatible License Added

> **Mode-dependent:** in `mode: proprietary`, adding a *permissive* open-source license is a warning rather than a block — see [Proprietary Mode](#proprietary-mode). Copyleft/AGPL/other restrictive licenses are unaffected and still block in both modes.

**What triggers this:**
- Adding code with a license that is not in the repository's allowed license list
- Introducing code under GPL, AGPL, or other copyleft licenses when the repository uses permissive licenses (BSD, MIT, Apache)
- Adding proprietary or restrictive licenses

**Example:**
```
🚨 BLOCKING ERROR:
📄 File: src/new_module.c
🚨 License issues detected:
  - Incompatible license added: GPL-2.0-only
```

**How to fix:**
- Remove the incompatible code
- Replace with code under a compatible license
- Obtain permission to relicense the code
- Add the license to the allowed list if it's actually compatible (requires approval)

**Compliance Impact:** HIGH - Mixing incompatible licenses can create legal issues and licensing conflicts

---

### 2. License Deletion Without Replacement

**What triggers this:**
- Removing license headers from existing files
- Deleting license statements without adding new ones
- Modifying files in a way that removes license information

**Example:**
```
🚨 BLOCKING ERROR:
📄 File: src/utils.py
🚨 License issues detected:
  - License deleted: BSD-3-Clause-Clear
```

**How to fix:**
- Restore the original license header
- Add an appropriate license header if it was missing
- Ensure license information is preserved during refactoring

**Compliance Impact:** HIGH - Removing license information can violate licensing terms and create legal ambiguity

---

### 3. License Change (Modification)

> **Mode-dependent:** in `mode: proprietary`, removing a proprietary rights statement is always a blocking error regardless of what replaces it, with a distinct message — see [Proprietary Mode](#proprietary-mode).

**What triggers this:**
- Changing the license of existing code from one license to another
- Replacing license headers with different licenses
- Modifying license terms

**Example:**
```
🚨 BLOCKING ERROR:
📄 File: src/core.cpp
🚨 License issues detected:
  - License deleted: MIT and license added: Apache-2.0
```

**How to fix:**
- Revert to the original license
- Obtain proper authorization for license changes
- Document the reason for license change if legitimate
- Ensure all copyright holders agree to the license change

**Compliance Impact:** CRITICAL - Changing licenses without proper authorization can violate copyright law

---

### 4. Missing License on New Source Files

> **Mode-dependent:** in `mode: proprietary`, a file carrying a recognized internal copyright is exempt from this rule, and the message differs when it isn't — see [Proprietary Mode](#proprietary-mode).

**What triggers this:**
- Adding new source code files without license headers
- Creating new modules without proper licensing information

**Supported source file extensions:**
```
.c, .cpp, .h, .hpp, .java, .py, .js, .ts, .rb, .go, .swift, .kt, .kts, .sh
```

**Example:**
```
🚨 BLOCKING ERROR:
📄 File: src/new_feature.py
🚨 License issues detected:
  - No license added for source file: src/new_feature.py
```

**How to fix:**
- Add appropriate license header to the file
- Use the repository's standard license template
- Include SPDX identifier for clarity


**Compliance Impact:** MEDIUM - New code without licenses creates ambiguity about usage rights

---

### 5. Copyright Deletion

**What triggers this:**
- Removing copyright statements from existing code
- Deleting copyright holder information
- Modifying copyright notices inappropriately

**Example:**
```
🚨 BLOCKING ERROR:
📄 File: src/algorithm.c
⚠️ Copyright issues detected:
  - Copyright deletions detected: ['Copyright (c) 2024 Original Author']
```

**How to fix:**
- Restore the original copyright statement
- Add your copyright in addition to (not replacing) existing copyrights
- Follow the pattern: keep old copyrights, add new ones

**Allowed Exception:**
The action allows the following copyright transition:
- FROM: "Qualcomm Innovation Center, Inc. All rights"
- TO: "Qualcomm Technologies, Inc. and/or its subsidiaries"

**Compliance Impact:** HIGH - Removing copyright notices can violate copyright law and attribution requirements

---

## Non-Blocking Warnings

The following scenarios generate **WARNINGS** but do NOT block the build:

### Uncertain/Unknown License Detection

**What triggers this:**
- Scancode detects uncertain or unknown license patterns
- Any `LicenseRef-scancode-*` license that is not in the known permissive list
- Ambiguous license text that scancode cannot confidently identify

**Specific patterns treated as warnings:**
- `LicenseRef-scancode-unknown-*` (e.g., `LicenseRef-scancode-unknown-license-reference`)
- `LicenseRef-scancode-warranty-disclaimer` (just a disclaimer, not a license)
- `LicenseRef-scancode-proprietary-*` (when mixed with other uncertain licenses)
- Any other `LicenseRef-scancode-*` not explicitly in the permissive list

**How it works:**
The action intelligently evaluates license expressions:
1. If ALL licenses in the expression are uncertain/unknown → **WARNING**
2. If ANY license is a known incompatible license (GPL, AGPL, etc.) → **BLOCKING ERROR**
3. Mixed uncertain licenses are treated as warnings to allow manual review

**Example - Warning:**
```
⚠️ WARNINGS (Non-blocking):
📄 File: src/vendor/third_party.c
⚠️ License warnings:
  - Incompatible license added: LicenseRef-scancode-unknown-license-reference AND LicenseRef-scancode-proprietary-license AND LicenseRef-scancode-warranty-disclaimer
```

**Example - Blocking Error (mixed with known incompatible):**
```
🚨 BLOCKING ERROR:
📄 File: src/module.c
🚨 License issues detected:
  - Incompatible license added: GPL-2.0-only AND LicenseRef-scancode-unknown-license-reference
```
*This blocks because GPL-2.0-only is a known incompatible license*

**What to do:**
- Manually review the file to identify the actual license
- Add proper license headers if missing or unclear
- Update the code to use clear, standard SPDX license identifiers
- Consider adding the file to `.licenseignore` if it's a known false positive or vendored dependency
- If the license is genuinely unknown, work with the code owner to clarify licensing

**Why this is a warning, not an error:**
Scancode may flag licenses as "unknown" due to:
- Non-standard license formatting
- Partial or truncated license text
- Custom license variations
- Detection algorithm limitations

These cases require human review but shouldn't automatically block development, as they may be false positives or require clarification rather than immediate remediation.

**Compliance Impact:** LOW - Requires manual review but doesn't block development. However, unresolved unknown licenses should be addressed before production release.

---

### Special Case: Sole Proprietary License

> **Mode-dependent:** this section describes `mode: opensource` (the default). In `mode: proprietary` a sole proprietary detection is *expected* and raises no issue at all, unless the same change deletes a license of its own — see [Proprietary Mode](#proprietary-mode).

**What triggers this:**
- A file contains ONLY `LicenseRef-scancode-proprietary-license` with no other licenses

**Example - Blocking Error:**
```
🚨 BLOCKING ERROR:
📄 File: src/proprietary.c
🚨 License issues detected:
  - Incompatible license added: LicenseRef-scancode-proprietary-license
```

**Why this blocks:**
When scancode identifies a file as having ONLY a proprietary license (not mixed with other uncertain licenses), it's a clear indication of incompatible licensing that should be addressed immediately.

**How to fix:**
- Remove the proprietary code
- Replace with code under a compatible license
- Add proper open-source license headers
- Obtain permission to relicense the code

**Note:** If `LicenseRef-scancode-proprietary-license` appears mixed with other uncertain licenses (e.g., `LicenseRef-scancode-unknown-*`), it's treated as a warning for manual review, as this may indicate scancode detection ambiguity rather than actual proprietary code.

**Compliance Impact:** HIGH - Proprietary code in open-source repositories creates licensing conflicts

---

## Proprietary Mode

By default this action assumes it is checking an **open-source** repository. Set `mode: proprietary` to check an internally-developed proprietary codebase instead, where Qualcomm-authored files carry a proprietary rights statement rather than an OSS license.

```yaml
- name: Run copyright/license detector
  uses: qualcomm/copyright-license-checker-action@main
  with:
    patch_file: pr.patch
    repo_name: ${{ github.repository }}
    mode: proprietary
```

### Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `mode` | `opensource` | `opensource` or `proprietary`. Any other value fails immediately. |
| `proprietary_entities` | *(empty)* | Comma-separated extra copyright-holder strings treated as internal authorship, **in addition to** the built-in defaults. Entity names cannot contain commas, since a comma is the field separator. |

The built-in internal entities are `Qualcomm Technologies, Inc.` and `Qualcomm Technologies, Inc. and/or its subsidiaries`.

### Proprietary repositories have no LICENSE file

This is expected and correct — a proprietary repository is not distributed under an open-source license. In `proprietary` mode the action does **not** scan for a `LICENSE`/`COPYING` file at all, and license compatibility is judged against the built-in permissive-license list directly.

### What changes in proprietary mode

Everything not listed here behaves exactly as documented above. In particular, **copyleft licenses, license deletions, license modifications, and copyright deletions are all still blocking errors** — proprietary mode does not relax legal or compliance risk, only the open-source-versus-proprietary judgment calls.

#### 1. Removing a proprietary rights statement — BLOCKING

Deleting a proprietary marking is a blocking error regardless of what replaces it. Replacing a proprietary header with a permissive open-source license is still a removal of the marking, and blocks.

```
🚨 BLOCKING ERROR:
📄 File: src/internal_module.c
🚨 License issues detected:
  - Proprietary license statement removed: LicenseRef-scancode-proprietary-license -- removing a proprietary rights statement requires review; restore it, or route the change to the scan team/legal if the file's status has genuinely changed.
```

**How to fix:** restore the statement. If the file's licensing status has genuinely changed, route the change to the scan team/legal rather than making the change unilaterally.

This is detected per-component, so removing the marker from a compound expression such as `LicenseRef-scancode-proprietary-license AND GPL-2.0-only` also blocks. A marking present unchanged on both sides of the diff (for example a reformatted header) is not a removal.

#### 2. Adding permissive open-source code — WARNING

Vendoring permissive OSS (MIT, BSD, Apache-2.0, …) into a proprietary repository is allowed, but warns so a human reviews it and records the attribution.

```
⚠️ WARNINGS (Non-blocking):
📄 File: src/vendor/third_party.c
⚠️ License warnings:
  - Permissive open-source license added: MIT -- review that this third-party code is approved for inclusion, and update the repo's NOTICE file with the required attribution.
```

**What to do:**
- Confirm the third-party code is approved for inclusion
- **Update the repository's `NOTICE` file** with the required attribution

This applies whether the file was previously unmarked or keeps its proprietary marking (for example a file detected as `MIT AND LicenseRef-scancode-proprietary-license`). It does not fire for a license that is unchanged across the diff. Copyleft additions are unaffected and still block, even alongside a retained proprietary marking.

#### 3. Sole proprietary license detection — NO ISSUE

A file detected as only `LicenseRef-scancode-proprietary-license` is the normal case for an internal Qualcomm header and raises no issue. (In `opensource` mode this blocks — see the section above.)

This covers adding an internal header, and reformatting one that is already there. It does **not** extend to a change that gives up a license of its own: deleting a real license and marking the file proprietary in its place is a relicensing of third-party code, and still blocks as a license change (scenario 3 above).

```
🚨 BLOCKING ERROR:
📄 File: src/core.cpp
🚨 License issues detected:
  - License deleted: MIT and license added: LicenseRef-scancode-proprietary-license -- a permissive license's attribution terms are not extinguished by marking the file proprietary; restore the deleted license, or route the change to the scan team/legal if the file's licensing has genuinely changed.
```

**How to fix:**
- Restore the original license header — a permissive license's attribution terms survive vendoring into a proprietary repository
- If the file is genuinely Qualcomm-authored and the OSS header was there in error, route the change to the scan team/legal rather than removing the header yourself

#### 4. New source file with no license — BLOCKING, with different guidance

A new source file with no detected license is **not** blocked if it carries a copyright naming one of the recognized internal entities; that is the ordinary case for internal code. If it has neither a license nor a recognized internal copyright, it still blocks:

```
🚨 BLOCKING ERROR:
📄 File: src/new_module.c
🚨 License issues detected:
  - No license or internal copyright found for source file: src/new_module.c -- if this is third-party code, do NOT add a Qualcomm copyright; route it to the scan team/legal for review. If this is Qualcomm-authored code, add the appropriate copyright marking.
```

**How to fix — the two possibilities are different:**
- **Third-party code**: do **not** add a Qualcomm copyright to it. Route it to the scan team/legal for review.
- **Qualcomm-authored code**: add the appropriate copyright marking.

---

## License Categories

### Permissive Licenses (Generally Allowed)
```
BSD-3-Clause, MIT, Apache-2.0, BSD-3-Clause-Clear, ISC, CC0-1.0, Zlib
```

### Copyleft Licenses (Restricted)
```
GPL-2.0, GPL-3.0, AGPL-3.0, LGPL-3.0
```

**Note:** The specific allowed licenses depend on your repository's configuration in `scanner/config.py`

---

## Best Practices for Compliance

### 1. Always Include License Headers
Every source file should have a clear license header:

**Example:**
```
Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
SPDX-License-Identifier: BSD-3-Clause-Clear
```

### 2. Preserve Existing Copyrights
When modifying files:
- Keep all existing copyright statements
- Add your copyright below existing ones
- Never remove or modify existing copyright holders

### 3. Use Standard License Identifiers
- Use SPDX identifiers for clarity
- Avoid custom or ambiguous license text
- Reference standard license texts

### 4. Document Third-Party Code
- Clearly mark third-party code
- Include original license information
- Consider using `.licenseignore` for vendored dependencies

### 5. Review Before Committing
- Check license headers before committing
- Verify copyright statements are accurate
- Run the action locally if possible

---

## Exemptions and Overrides

### Using .licenseignore

Create a `.licenseignore` file at the repository root to exclude files from license checks:

```
# Ignore vendored dependencies
vendor/**
third_party/**

# Ignore generated files
*.generated.js
build/**

# Ignore test fixtures
tests/fixtures/**
```

**Use with caution:** Only ignore files where license checking is not applicable or creates false positives.

---

## Troubleshooting

### Build Blocked - What to Do?

1. **Read the error message carefully** - It tells you exactly what's wrong
2. **Check the specific file** mentioned in the error
3. **Review the compliance scenario** that matches your error
4. **Apply the recommended fix**
5. **Test locally** if possible before pushing

### Common Mistakes

❌ **Removing license headers during refactoring**
✅ Preserve all license information when restructuring code

❌ **Copying code without preserving licenses**
✅ Always maintain original license and copyright information

❌ **Adding GPL code to BSD-licensed projects**
✅ Verify license compatibility before adding third-party code

❌ **Forgetting license headers on new files**
✅ Use templates or IDE snippets to add headers automatically

---

## Contact and Support

### For Internal Developers

**Contact:** lost.dev  
**POC:** targoy (Tarun Goyal)

For questions about license compliance or to request exemptions:
- Review your organization's open source compliance policies
- Consult with your legal team for complex licensing questions
- File an issue in the action repository for technical problems
- Reach out to the POC for internal support and guidance

---
