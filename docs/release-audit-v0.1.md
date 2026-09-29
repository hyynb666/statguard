# StatGuard v0.1 Release Readiness Audit

**Audit scope:** repository preparation only. No package publication, version
tag, or GitHub Release is part of this audit.

**Decision:** **READY FOR RELEASE ISSUE** — the repository is prepared for a
separately reviewed v0.1 release issue. This is not authorization to publish a
release.

**Baseline:** main `a484566` before this audit; Python 3.11+; CLI and JSON
contract in [reporting.md](reporting.md).

## Readiness checklist

`PASS` means the item was present and verified; `FIXED IN THIS ISSUE` means
this audit added or reconciled it; `BLOCKED` means a release-preparation
requirement remains unmet; `NOT IN SCOPE` means it belongs to a later, separately
authorized release operation.

| Area | Status | Evidence / notes |
| --- | --- | --- |
| v0.1 rule completeness | PASS | ML001–ML006 and ST001–ST002 are registered and covered; an automated registry contract test checks these IDs and uniqueness. |
| Additional rules | PASS | ML009 is registered and documented as additional; it is not included in the eight-rule core count. |
| CLI completeness | PASS | `check`, `--help`, `--version`, Python module entry point, Console/JSON/HTML, output, exclusions, disable-rule, and fail threshold are implemented and tested. |
| Exit-code documentation | FIXED IN THIS ISSUE | PRD, AGENTS, README, and reporting guide now state the same default and `--fail-on` behavior. |
| Python support | PASS | Requires Python 3.11+; CI tests 3.11–3.14 on Windows and Linux. |
| Notebook support | PASS | Python cells are parsed independently with cell locations; outputs and kernel history are not analyzed. |
| No-execution safety | PASS | Parser/scanner tests use side-effect fixtures; static AST/import analysis does not import or run submitted code. |
| Console Reporter | PASS | Renders Finding location, evidence, risk, recommendation, totals, and scan errors. |
| JSON Reporter | PASS | Schema 1.0 documents findings, file summaries, errors, notices, evidence, and cell locations. |
| HTML Reporter | PASS | Offline report; dynamic content escaped; fixed script pinned by CSP; no remote resources. |
| Packaging | PASS | `pyproject.toml` declares src-layout package, Python requirement, license, entry point, dependencies, and project links; CI builds and installs a wheel. |
| CI | PASS | Existing workflow runs Ruff, tests, CLI smoke, and package build/install on Linux and Windows across Python 3.11–3.14. |
| README | FIXED IN THIS ISSUE | Adds purpose, rule matrix, real CLI diagnostic, source installation, limits, Notebook behavior, report command, and governance links. |
| License | PASS | MIT license is present and declared in package metadata. |
| CONTRIBUTING | FIXED IN THIS ISSUE | Existing development/test/rule guidance retained; PR process and governance/security links added. |
| Code of Conduct | FIXED IN THIS ISSUE | Contributor Covenant 2.1-based policy added. |
| Security policy | FIXED IN THIS ISSUE | Private reporting path is conditional on GitHub availability; no nonexistent email is claimed. |
| Issue templates | FIXED IN THIS ISSUE | Bug and feature forms collect required environment, reproduction, evidence, and false-positive details; they warn against submitting secrets/private data. |
| Pull request template | FIXED IN THIS ISSUE | Captures behavior, statistical rationale, false-positive review, tests, safety, compatibility, and rule-specific evidence. |
| Changelog | FIXED IN THIS ISSUE | Unreleased entry reflects existing capabilities and limitations; no fabricated release date. |
| Installation documentation | FIXED IN THIS ISSUE | README directs users to source/editable installation and explicitly states the package is not on PyPI. |
| Rule documentation | PASS | ML001–ML006, ML009, ST001, and ST002 have purpose, supported patterns, behavior examples, evidence/metadata, and limitations; gaps found in metadata statements were filled. |
| Evidence categories | PASS | Rules use the shared evidence vocabulary; JSON and report guide document evidence fields. |
| JSON schema documentation | PASS | `docs/reporting.md` describes schema version 1.0 and top-level, Finding, error, and notice fields. |
| Notebook-order limitations | PASS | README, parser/report docs, and rule guides state that document order is not execution history and cross-cell flow is not modeled. |
| Known limitations | PASS | README, rule docs, and this audit bound supported static patterns; a clean scan is not a correctness guarantee. |
| Local Markdown links | FIXED IN THIS ISSUE | A small pytest contract checks repository-local Markdown links. |
| Rule matrix | FIXED IN THIS ISSUE | README distinguishes the eight v0.1 core rules from additional ML009. |
| Examples / sample diagnostic | FIXED IN THIS ISSUE | Three small source examples were scanned with the installed CLI; README output was captured from that run. |
| Performance sanity | PASS | Project test tree and small examples scan deterministically without runaway traversal; no numeric SLA is claimed. |
| Windows/Linux behavior | PASS | CI covers both operating systems; new files and examples use platform-neutral content. |
| Version metadata | PASS | Version remains `0.1.0.dev0`; package metadata includes repository, issues, documentation, and changelog URLs. |
| Release classifier freeze | NOT IN SCOPE | Current classifier remains Pre-Alpha; review/update it to Alpha when the release version is frozen. |
| PyPI installation/publication | NOT IN SCOPE | PyPI is not currently published and no upload, token, trusted publisher, or publish workflow was created. Test the uploaded artifact only in a separately authorized release task. |
| Version tag / GitHub Release | NOT IN SCOPE | No tag or Release was created; follow [release-checklist.md](release-checklist.md) in the release issue. |
| Formal release date | NOT IN SCOPE | Changelog uses Unreleased and contains no invented date. |

## Exit-code contract

The CLI returns:

- `0` when scanning completes and no explicitly configured failure threshold
  is met. Findings do not fail by default.
- `1` when a Finding meets `--fail-on warning` or `--fail-on error`.
- `2` for invalid invocation or an input, parse, rule, or report error.

This is the single v0.1 policy documented in the PRD, README, AGENTS, and
reporting guide. An undetermined notice alone does not trigger a threshold.

## Release gate and remaining work

No repository-hardening blocker remains for opening a dedicated v0.1 release
issue. That issue must run the [release checklist](release-checklist.md), freeze
the changelog/version/classifier, verify release artifacts, and obtain explicit
authorization for any tag, GitHub Release, or PyPI publication. The current
audit does not claim StatGuard is already published or that a clean scan proves
statistical correctness.
