# StatGuard v1.0.0 Release Checklist

This checklist records the v1.0.0 release gates and execution state. Release
actions are checked only after they are verified. PyPI publication is outside
the release scope and is not authorized.

## Audit and compatibility gates

- [x] Issue #32 audit decision is `READY FOR v1.0.0 RELEASE`.
- [x] All 11 default rules (ML001–ML009, ST001, ST002) have implementation,
  tests, and rule documentation.
- [x] Baseline full pytest, Ruff lint, Ruff format, and diff checks passed.
- [x] Baseline CI covered Windows/Linux and Python 3.11–3.14 and passed.
- [x] Baseline wheel and sdist built and installed in isolated environments.
- [x] Compatibility contracts cover JSON 1.0, CLI/exit codes, config,
  suppression, GitHub Action inputs, SARIF 2.1.0, and `statguard.core`.
- [x] Audit reviewed no-execution, Notebook-output isolation, HTML escaping/CSP,
  Action path/shell safety, deterministic output, and runtime dependencies.
- [x] Release notes, README wording, and historical v0.1/v0.2 records were
  reviewed without changing release history.
- [x] The v1 classifier is Beta; Production/Stable is not claimed.

## Release execution

- [x] Freeze package version at `1.0.0` and freeze the changelog for
  `2026-09-30`.
- [ ] Merge the reviewed release PR and confirm its CI.
- [ ] Create and push annotated tag `v1.0.0` on the release merge commit.
- [ ] Build final wheel and sdist from the tag; inspect contents and verify
  SHA-256 checksums.
- [ ] Publish the non-draft, non-prerelease GitHub Release with the wheel,
  sdist, and `SHA256SUMS.txt`; verify all assets.
- [x] Confirm v0.1.0 and v0.2.0 tags, Releases, and assets are preserved.
- [x] Confirm no PyPI publish operation or credential setup is part of this
  release.

After the release gates complete, the final report records their verified
state. This checklist is not permission to publish to PyPI or start another
development cycle.
