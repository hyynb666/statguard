# StatGuard v0.2.0 Release Checklist

This checklist is specific to v0.2.0. The [v0.1.0 checklist](release-checklist.md)
remains an unchanged historical record. PyPI publication is not authorized.

## Release preparation

- [ ] Start from a clean `main` synchronized with `origin/main`.
- [ ] Review `release-audit-v0.2.md`; proceed only with `READY FOR v0.2.0 RELEASE`.
- [ ] Confirm the enabled rule IDs are ML001–ML006, ML009, ST001, and ST002;
  confirm no rule semantics changed for this release.
- [ ] Run the full pytest suite; explain the two expected Windows symlink skips.
- [ ] Run Ruff lint, Ruff format check, and `git diff --check`.
- [ ] Build sdist and wheel and inspect wheel metadata and runtime dependencies.
- [ ] Install the wheel in a fresh isolated environment; check both CLI version
  entry points, help, Console, JSON schema 1.0, HTML/CSP, SARIF 2.1.0, project
  configuration, Notebook handling, and no-execution fixtures.
- [ ] Smoke-test the GitHub Action on Linux and Windows, including config,
  outputs, exclusions, thresholds, rule disabling, workspace boundaries, and
  no-execution behavior.
- [ ] Freeze version `0.2.0`, Alpha classifier, `[Unreleased]`, and dated
  `0.2.0` changelog entry; keep the v0.1.0 history unchanged.
- [ ] Review README, release notes, stable `@v0.2.0` Action examples, local
  Markdown links, and the explicit not-on-PyPI statement.
- [ ] Confirm release PR CI and review are clear, then merge normally.
- [ ] Confirm the main push CI is completed and successful before tagging.

## Tag and artifacts

- [ ] Create annotated tag `v0.2.0` on the release merge commit with message
  `StatGuard v0.2.0`; push only that tag and verify the remote target.
- [ ] Confirm the v0.1.0 tag and GitHub Release are unchanged.
- [ ] Build from a clean checkout of the v0.2.0 tag, not an intermediate branch
  state.
- [ ] Place only `statguard-0.2.0-py3-none-any.whl`,
  `statguard-0.2.0.tar.gz`, and `SHA256SUMS.txt` in
  `build/issue26-final-release-dist`.
- [ ] Reinstall the tag-built wheel in a fresh environment, verify version
  `0.2.0`, CLI/report/config behavior, and source/Notebook no-execution.
- [ ] Verify SHA-256 checksums for exactly the wheel and sdist.

## GitHub Release and post-release

- [ ] Create the ordinary (not draft, not pre-release) GitHub Release titled
  `StatGuard v0.2.0` from tag `v0.2.0`, using `docs/releases/v0.2.0.md`.
- [ ] Upload exactly the wheel, sdist, and checksum file; verify all three
  remote assets and release metadata.
- [ ] Verify README's release URL, the tag's Action and SARIF/config sources,
  and remote asset installation if download access permits.
- [ ] Confirm local `main` equals `origin/main` and the working tree is clean.
- [ ] Do not publish to PyPI or bump to a development version in this issue.
