# StatGuard v1.0.0 release checklist (draft)

This checklist records audit gates for a possible v1.0.0 release. It does not
perform release actions. Version freezing, tag creation, GitHub Release
publication, artifact upload, checksum generation, and any package publication
belong to a separately authorized release task.

## Audit and compatibility gates

- [ ] Review `docs/release-audit-v1.0.md` and resolve every blocker.
- [ ] Confirm all 11 default rule IDs have implementation, tests, and rule
  documentation: ML001–ML009, ST001, and ST002.
- [ ] Confirm local pytest, Ruff lint, Ruff format, and diff checks pass.
- [ ] Confirm CI covers Windows/Linux and Python 3.11–3.14 and passes on the
  release candidate commit.
- [ ] Build and inspect both wheel and sdist; install each in fresh isolated
  environments and run CLI/API smoke checks.
- [ ] Confirm JSON schema 1.0, CLI/exit codes, project configuration, inline
  suppression, GitHub Action inputs, SARIF 2.1.0, and `statguard.core` exports
  match `docs/compatibility.md`.
- [ ] Recheck no-execution, Notebook-output isolation, report escaping/CSP,
  Action path/shell safety, deterministic output, and runtime dependency policy.
- [ ] Review draft release notes, README links, and current/stable tag wording.
- [ ] Review the package Development Status classifier. The current metadata is
  Alpha; the audit recommends **Beta** for v1.0.0, not Production/Stable.

## Release actions — pending separate authorization

- [ ] Freeze package version and `[Unreleased]` changelog for the approved
  release date.
- [ ] Merge the separately reviewed release PR and verify main CI.
- [ ] Create and push the approved annotated v1.0.0 tag.
- [ ] Build final artifacts from the tag; verify wheel/sdist contents and
  SHA-256 checksums.
- [ ] Create the GitHub Release from v1.0.0, attach only approved artifacts,
  and verify the release page and assets.
- [ ] Confirm v0.1.0 and v0.2.0 tags, Releases, and assets remain unchanged.
- [ ] Confirm the project remains not published on PyPI unless a distinct
  future authorization explicitly changes that status.

No v1.0.0 version bump, tag, GitHub Release, release artifact upload, or PyPI
publication is performed by the Issue #32 audit.
