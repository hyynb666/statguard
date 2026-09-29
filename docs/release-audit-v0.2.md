# StatGuard v0.2.0 Release Readiness Audit

**Audit scope:** v0.2.0 release preparation at main baseline
`fbfea6381112ee6595b1a0f615b6a629594aa6ec`. This audit does not authorize or
perform PyPI publication.

**Decision: READY FOR v0.2.0 RELEASE**

The release contains integrations and project configuration, not new detection
rules. Findings remain conservative static-analysis prompts. This decision is
based on the source review and checks listed below; the release PR and main CI
are separate gates recorded in the release report.

## Audit results

| Area | Result | Evidence and release boundary |
| --- | --- | --- |
| Python parser | PASS | Uses the standard-library AST parser, preserves locations and explicit failures; parser tests and side-effect fixtures cover static-only handling. |
| Notebook parser | PASS | Parses Python code cells independently, keeps cell coordinates, reports unsupported syntax, and does not use stored outputs as analysis input. |
| Scanner and Analyzer | PASS | Deterministic file discovery, structured complete/partial/failed results, error separation, and continued scanning are covered by integration tests. |
| RuleRegistry and SymbolResolver | PASS | Rule selection is explicit; symbol resolution is binding/version-aware and conservative around dynamic behavior. |
| Data provenance | PASS | Existing supported assignments, estimator/test roles, fit events, and cross-validation transformations reuse the documented provenance model. No release change modifies it. |
| No-execution safety | PASS | Tests verify Python source, Notebook code, and Notebook outputs are not executed; config is parsed as TOML data. |
| Rule set | PASS | The default registry contains exactly ML001–ML006, ML009, ST001, and ST002. This release changes no rule code, IDs, evidence, severity, or behavior. |
| Console reporter | PASS | Shared Finding output, totals, and scan errors are covered by CLI and reporter tests. |
| JSON reporter | PASS | JSON schema remains version 1.0; the release does not change its structure. |
| HTML reporter | PASS | Offline report, escaped dynamic content, local resources, filters, and CSP are covered by reporter tests. |
| SARIF reporter | PASS | SARIF 2.1.0, Python locations, conservative Notebook cell properties, fingerprints, notifications, and no automatic upload are documented and tested. |
| CLI | PASS | `check`, report formats, output, exclusions, failure thresholds, disabling rules, config selection, and `--no-config` are covered. Exit codes remain 0/1/2 as documented. |
| Project configuration | PASS | `[tool.statguard]` accepts only `exclude`, `disable-rules`, and `fail-on`; strict validation uses standard-library `tomllib`. |
| GitHub Action | PASS | Input validation, workspace containment, installation from `GITHUB_ACTION_PATH`, argv invocation with `shell=False`, and Linux/Windows smoke checks are present. The Action does not upload reports. |
| Packaging | PASS | `src` layout, Python `>=3.11`, empty runtime dependencies, MIT metadata, console entry point, sdist and wheel build are verified. Development Status remains Alpha. |
| Governance | PASS | MIT license, contribution guide, security policy, Code of Conduct, issue forms, and pull request template are present. |
| Documentation | PASS | README and Action/SARIF examples are frozen to v0.2.0; the v0.1.0 audit, checklist, notes, tag, and Release remain historical. Local Markdown links are tested. |

## v0.2.0 scope

The release adds:

- GitHub Composite Action integration.
- `[tool.statguard]` project policy through `pyproject.toml`.
- SARIF 2.1.0 output and GitHub Code Scanning guidance.
- Workspace-contained Action inputs/outputs and corresponding safety checks.

The enabled rule IDs remain **ML001–ML006, ML009, ST001, and ST002**. The
release does not add ML007 or ML008, change rule semantics, alter JSON schema
1.0, or add runtime dependencies.

## Validation basis

- Main baseline matched the authorized commit and `origin/main`; the working
  tree was clean before release preparation.
- Baseline full suite: 884 passed, 2 skipped. Both skips are Windows symlink
  creation limitations.
- Release-preparation suite after metadata and documentation checks: 886 passed,
  2 skipped. The two skips are the same Windows symlink creation limitations;
  no other tests were skipped.
- CI on the baseline passed all 11 jobs, including Python 3.11–3.14 on Windows
  and Linux, package build, and Action smoke tests on both platforms.
- Ruff lint and formatting pass, and `git diff --check` is clean on the release
  branch. A v0.2.0 candidate sdist/wheel builds; a fresh isolated wheel
  installation passes metadata, CLI, Console/JSON/HTML/SARIF, project config,
  and Python/Notebook no-execution smoke tests.
- The PR and main CI results will be recorded in the final release report.

## Blockers and decision

No code, API, packaging, safety, or governance blocker is known. StatGuard is
not published to PyPI; this release uses tagged source and GitHub artifacts.
That is an explicit scope boundary, not a release blocker.

**READY FOR v0.2.0 RELEASE**
