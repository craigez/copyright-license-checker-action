# Reusable CLI Plan

## Objective

Turn the checker into an installable command-line application that can be run
locally, in other CI systems, or by the existing GitHub Action.

The CLI is the supported interface. The internal Python modules may remain
importable for tests and implementation purposes, but they will not be treated
as a stable public library API.

## Current State

The repository already contains most of a CLI:

- `main.py` uses `argparse` and accepts a patch file, repository name, mode,
  and proprietary entity overrides.
- It returns exit code `0` for a clean or warnings-only result and `1` for
  blocking findings.
- GitHub workflow annotations are only emitted when `GITHUB_ACTIONS=true`.
- The GitHub Action invokes `main.py` directly after installing
  `requirements.txt`.

The remaining limitations are packaging and portability:

- There is no installable project metadata or console-script entry point.
- Users must know the repository layout and invoke `python main.py`.
- License discovery and `.licenseignore` loading depend implicitly on the
  process working directory.
- The `scanner` package name is generic and could conflict with other installed
  packages.
- Installation, CLI invocation, and wheel/sdist behavior are not tested.
- Documentation only presents the GitHub Action workflow.

## Proposed CLI Contract

The installed command will be named `copyright-license-checker`:

```sh
copyright-license-checker PATCH_FILE [REPO_NAME] [OPTIONS]
```

Initial options:

```text
--repo-root PATH
--mode {opensource,proprietary}
--proprietary-entities ENTITY[,ENTITY...]
--version
```

Behavior:

- `PATCH_FILE` is the Git-format patch to inspect.
- `REPO_NAME` remains accepted for compatibility with the Action and existing
  scripts. When omitted, it defaults to the repository-root directory name.
- `--repo-root` identifies the checkout whose `LICENSE`, `COPYING`, and
  `.licenseignore` files apply. It defaults to the current directory.
- Relative patch paths are resolved from the caller's current directory, not
  from `--repo-root`.
- The CLI continues to produce the existing human-readable report.
- GitHub annotations remain an environment-specific enhancement and do not
  affect normal local output.

Exit codes will be an explicit compatibility contract:

| Code | Meaning |
| ---: | --- |
| `0` | No blocking findings; warnings may be present |
| `1` | One or more blocking compliance findings |
| `2` | Invalid arguments or invalid user-supplied paths/configuration |
| `3` | Checker execution failed, for example because ScanCode could not run |

The first release will continue to require a pre-generated patch. Generating a
Git diff, scanning an entire repository, JSON/SARIF output, plugin APIs, and a
stable Python API are outside this migration's scope.

## Target Layout

Use a `src` layout so tests exercise the installed package rather than
accidentally importing files from the repository root:

```text
src/
  copyright_license_checker/
    __init__.py
    __main__.py
    cli.py
    config.py
    copyright_checker.py
    file_types.py
    ignore_config.py
    license_scancode.py
    licenses.py
    patch.py
tests/
pyproject.toml
requirements.txt
action.yml
```

`cli.py` will own argument parsing, report rendering, environment-specific
annotations, and exit-code selection. Checker modules will return findings or
raise typed operational errors; they will not terminate the process.

`__main__.py` will make this development/debugging form work as well:

```sh
python -m copyright_license_checker --help
```

## Incremental Implementation

Each group below should be implemented, tested, and committed independently.

### 1. Define the CLI behavior with tests

- Add subprocess-level tests for help output, argument validation, exit codes,
  and execution from a directory other than the source checkout.
- Add tests that distinguish `PATCH_FILE` resolution from `--repo-root`
  resolution.
- Pin the current text-report and GitHub-annotation behavior so packaging work
  does not silently alter compliance results.
- Add tests for missing/unreadable patches, invalid repository roots, and a
  missing or failed ScanCode executable.

Suggested commit:

```text
test(cli): define reusable command behavior
```

### 2. Move implementation into a namespaced package

- Create `src/copyright_license_checker` and move the current `scanner`
  modules into it.
- Move entry-point orchestration from `main.py` into `cli.py`.
- Add `__main__.py` as a minimal wrapper around `cli.main()`.
- Replace implicit current-directory reads with explicit `repo_root` paths.
- Pass the `.licenseignore` path into `Patch`/`IgnoreConfig` rather than letting
  those classes inspect the process working directory.
- Use `pathlib.Path` for user-supplied paths and validate them before scanning.
- Introduce specific operational exceptions so CLI failures can map to exit
  code `3` without exposing a traceback during normal use.
- Keep compatibility behavior in a temporary root `main.py` wrapper until the
  Action is migrated.

Suggested commit:

```text
refactor(cli): move checker into namespaced package
```

### 3. Add installable packaging and the console command

- Add PEP 517 build-system and project metadata to `pyproject.toml`.
- Declare Python 3.12 support, the project license, runtime dependencies, and
  the `copyright-license-checker` console script.
- Keep dependency declarations in one authoritative location. If
  `requirements.txt` remains for the Action or container checks, generate it or
  clearly document how it is synchronized with `pyproject.toml`.
- Ensure ScanCode's command is installed with the application and preserve the
  wheel-only `lxml` constraint needed by the Action environment.
- Add a version source used by both package metadata and `--version`.
- Update tox so tests install the package rather than relying on `PYTHONPATH`.
- Build both a wheel and source distribution and verify their contents.

Suggested commit:

```text
feat(cli): add installable console command
```

### 4. Make the GitHub Action consume the installed CLI

- Install the local project from `github.action_path` in `action.yml`.
- Invoke `copyright-license-checker` instead of reaching into `main.py`.
- Pass the checked-out workspace explicitly through `--repo-root`.
- Preserve all existing Action inputs and defaults.
- Keep `GITHUB_ACTIONS=true` behavior so workflow annotations remain
  available.
- Add or update tests that compare direct CLI results with Action-style
  invocation.

Suggested commit:

```text
refactor(action): invoke packaged checker CLI
```

### 5. Document local and CI usage

- Add installation examples for a local checkout and `pipx`/`pip`.
- Document how to generate a patch with Git before invoking the checker.
- Show open-source and proprietary examples.
- Document `--repo-root`, `.licenseignore`, exit codes, and the ScanCode
  dependency.
- Add a generic CI example that does not rely on GitHub Actions.
- Retain the existing GitHub Action instructions as a separate usage path.

Suggested commit:

```text
docs(cli): document installation and standalone usage
```

### 6. Remove compatibility scaffolding

- Remove the root `main.py` wrapper after the Action, tests, and documentation
  use the installed command.
- Remove the old top-level `scanner` package and obsolete import-path setup.
- Confirm the source distribution, wheel, Action, and direct command all run
  the same implementation.

Suggested commit:

```text
chore(cli): remove legacy script entry point
```

## Verification for Every Functional Group

Run the repository's standard checks:

```sh
tox -q
```

For packaging-related groups, also run:

```sh
python -m build
python -m pip install --force-reinstall dist/*.whl
copyright-license-checker --help
copyright-license-checker --version
```

Use an isolated temporary environment for the wheel smoke test so it does not
depend on the source checkout. The existing real-ScanCode container check
should remain the integration test for native ScanCode dependencies.

## Acceptance Criteria

The migration is complete when:

- `pip install .` creates a `copyright-license-checker` command.
- The command works from outside the source checkout.
- Repository-level files are resolved through `--repo-root`, independent of
  the caller's current directory.
- Clean, warning, violation, usage-error, and operational-error exit codes
  match the documented contract.
- The GitHub Action invokes the packaged command and retains its current inputs,
  output, annotations, and compliance decisions.
- A wheel and source distribution build successfully and contain all required
  modules and metadata.
- The full tox suite and the real-ScanCode container check pass.
- Standalone CLI installation and usage are documented in `README.md`.

## Risks and Mitigations

- **ScanCode installation size and native dependencies:** keep the existing
  real-container test and wheel-only `lxml` installation validation.
- **Behavior changes during package moves:** establish subprocess-level CLI
  tests before moving modules and keep report snapshots during the migration.
- **Working-directory regressions:** pass `repo_root` explicitly and test from
  unrelated directories.
- **Duplicate dependency declarations:** use one authoritative dependency list
  and validate any exported requirements file in CI.
- **Breaking existing Action consumers:** preserve Action inputs and keep a
  temporary `main.py` compatibility wrapper until Action migration is proven.
