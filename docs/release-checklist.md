# StatGuard v0.1.0 Release Checklist

This checklist records the StatGuard v0.1.0 release process authorized by
Issue #22. PyPI publication remains out of scope and is not authorized.

## Pre-release

- [ ] Start from a clean `main` synchronized with `origin/main`.
- [ ] Run the full pytest suite and Ruff lint/format checks.
- [ ] Build sdist and wheel; install the wheel in a fresh isolated environment.
- [ ] Smoke-test `statguard --help`, `statguard --version`, and
  `python -m statguard --version`.
- [ ] Scan Python, Notebook, and example inputs; verify output and exit policy.
- [ ] Recheck that Python/Notebook source and Notebook outputs are not executed
  or used as analysis semantics.
- [ ] Review README, rule guides, JSON schema, limitations, and local links.
- [ ] Freeze the `[Unreleased]` changelog into a dated release entry only when
  the release date is known.
- [ ] Update `pyproject.toml` from `0.1.0.dev0` to the approved release version
  and review the Development Status classifier (expected Alpha at first
  public release).
- [ ] Confirm the release PR has passed all GitHub Actions jobs.

## Release

- [ ] Merge the reviewed release PR normally; verify main CI is green.
- [ ] Create an annotated version tag following the project's tag policy.
- [ ] Create the GitHub Release from that tag and review its notes/artifacts.
- [ ] Verify the release page and referenced source/wheel artifacts.

## Post-release

- [ ] Verify installation from the published source/wheel artifacts.
- [ ] If PyPI publication is separately approved, verify `pip install statguard`
  from PyPI only after upload; do not imply availability before then.
- [ ] Open a separate development-version change if the project chooses to do so.

## PyPI status

**Not part of this release-audit issue.** No PyPI token, publishing workflow,
Trusted Publisher, or upload is configured or authorized by this checklist.
