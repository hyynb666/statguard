# StatGuard v1.0.0 Release Audit

**Audit date:** 2026-09-30  
**Source baseline:** `785185f16584c0cb2973bf1e80c5ccd1f6fa81e7`  
**Baseline tree:** `390247a9e9ad0749f9a0e9abdaab9acf76cce4f3`  
**Audited development version:** `0.3.0.dev0`  
**Release target:** planned `v1.0.0`; no v1.0.0 tag or Release is created here.

This audit checks the current documented contracts and release readiness. It does not claim that static analysis understands arbitrary statistical workflows. The v0.1.0 and v0.2.0 tags, Releases, and assets are historical and remain unchanged. No package was published to PyPI.

## Audit results

| Area | Result | Evidence and boundary |
| --- | --- | --- |
| Rule inventory | PASS | The default registry contains exactly ML001–ML009 and ST001–ST002, each once. All 11 rule guides exist; full pytest covers each rule and registry uniqueness. The eight v0.1 core rules remain distinct from the additional ML009 rule. |
| Parser and static safety | PASS | Python source is parsed with `ast`. Notebook Python cells are analyzed independently; stored outputs are excluded from rule input. Full tests and installed-wheel side-effect fixtures confirm submitted Python, Notebook code, and Notebook outputs are not executed. |
| Provenance and Analyzer | PASS | The current Analyzer, SymbolResolver, and provenance interfaces are exercised by the complete regression suite. Rules consume parser/context evidence; unresolved dynamic and cross-scope relations remain bounded or abstain. |
| CLI and exit contract | PASS | `statguard check`, `--help`, `--version`, `python -m statguard`, report formats, configuration, suppression, and 0/1/2 exit behavior pass local and installed-wheel checks. Findings do not fail by default. |
| JSON contract | PASS | JSON remains schema `1.0`, parseable, deterministic, and includes summary, files, findings, analysis errors, and notices. The installed wheel produced valid JSON with Finding locations and evidence. |
| SARIF | PASS | The installed wheel emitted parseable SARIF `2.1.0` with a real Finding and no invented source snippets. SARIF remains distinct from JSON and is not uploaded automatically. |
| HTML | PASS | The installed wheel emitted an offline HTML report with a restrictive Content Security Policy and Finding content. Reporter tests cover escaping and interactive behavior; generated report smoke contained no remote resource URL. |
| Configuration and suppression | PASS | Auto-discovery, explicit `--config`, `--no-config`, same-line ignore, and next-line ignore passed installed-wheel smoke. Unknown/dynamic content is not treated as a suppression or a finding. |
| GitHub Action | PASS | Nine current inputs are documented: `path`, `python-version`, `format`, `output`, `fail-on`, `disable-rules`, `exclude`, `config`, and `no-config`. The runner uses argument arrays and `shell=False`, installs from `GITHUB_ACTION_PATH`, and contains resolved scan/config/output paths in the workspace. Baseline CI covers Linux and Windows Action smoke. |
| Public Python API | PASS | `statguard.__version__` and `Confidence`, `Evidence`, `Finding`, `Rule`, `RuleRegistry`, and `Severity` from `statguard.core` imported in both installed package environments. Other parser, context, analyzer, scanner, reporter, provenance, and module internals remain evolving unless separately listed. |
| Dependencies and metadata | PASS | `pyproject.toml` declares Python `>=3.11`, MIT, version `0.3.0.dev0`, and an empty runtime dependency list. Optional build/pytest/Ruff tools are marked as the `dev` extra. The current classifier remains Alpha by instruction. |
| Wheel and sdist | PASS | Both artifacts built as `0.3.0.dev0`; the wheel contains the `statguard` package and distribution metadata, with no `.git`, build/dist, cache, tests, or benchmark script. Fresh venv installs and external-cwd CLI/API smoke passed. The sdist test venv was bootstrapped offline with the already installed setuptools 84 build backend; no global environment was changed. |
| Installed-wheel self-scan | PASS | The freshly installed wheel scanned `src/statguard`: 40 files, 0 findings, 0 analysis errors. A zero-Finding self-scan is recorded as smoke evidence, not a correctness criterion. |
| Determinism and performance | PASS | The full suite includes cross-hash-seed report identity, many-file, Notebook-cell, and report-size regressions. Local synthetic benchmark smoke (14 files, repeat 3) completed with 0 errors; medium (220 files, repeat 1) completed with 0 errors. No timing gate or external speed comparison is claimed. The previously recorded Issue #31 reference is 220 files, median 0.356882 s, on its recorded Windows/Python host; this audit's run is not a before/after comparison. Stress was not repeated, consistent with the Issue #31 coverage. |
| Governance and security | PASS | MIT License, Code of Conduct, contribution guidance, SECURITY.md, issue forms, and PR template exist. SECURITY.md does not claim a response SLA or nonexistent security email. Source inspection and tests support no target execution, no runtime network client, TOML-as-data configuration, tokenized suppression comments, HTML escaping/CSP, Action shell/path safety, and SARIF without source snippets. |
| Documentation and history | PASS | All nine ML and two ST rule guides exist. README and contributor guidance distinguish stable v0.2.0 from the development line and draft v1 target. Historical v0.1/v0.2 documentation and release references were checked; README/Action stable references remain `@v0.2.0`. Local Markdown link validation is part of the test suite. |
| Current main CI | PASS | GitHub Actions run `36723456582` for baseline `785185f` completed successfully with 11/11 jobs, including Windows/Linux and Python 3.11–3.14. Audit PR and post-merge CI remain required integration gates and are reported separately after they run. |

## Compatibility boundary

The proposed v1 public compatibility boundary is specified in [compatibility.md](compatibility.md). It covers CLI option meaning and exit codes, the 11 rule IDs, JSON schema 1.0, `[tool.statguard]` keys, suppression grammar, the nine GitHub Action inputs, SARIF 2.1.0, and the named `statguard.core` exports. Internal/evolving interfaces are explicitly not granted the same guarantee. SemVer consequences and the stable v0.2.0 boundary are also recorded there.

## Metadata recommendation

The current package classifier is `Development Status :: 3 - Alpha` and remains unchanged. For the planned v1.0.0 release, this audit recommends `Development Status :: 4 - Beta`: the documented contracts have an explicit compatibility boundary, but static rule coverage is still limited and does not justify `Production/Stable`.

## Known non-blocking limitations

- Detection is limited to documented static patterns and selected sklearn and SciPy APIs; unsupported or dynamic patterns may be missed or left unknown.
- There is no arbitrary runtime introspection, cross-file data flow, or cross-Notebook-cell data flow. Notebook document order is not execution history.
- A clean scan does not prove statistical correctness; a Finding does not prove actual harm and may require human review.
- The Action writes reports but does not upload them. There is no IDE extension or server/dashboard backend.
- The package is not published on PyPI.
- Benchmark timings are host-dependent and are not an SLA.
- The Development Status classifier is still Alpha until a separately authorized release freeze.

No high-impact correctness, compatibility, safety, or packaging blocker was identified in the audited baseline. CI and review for the audit PR, and main CI after merge, are still mandatory merge gates.

## Decision

**READY FOR v1.0.0 RELEASE**

This decision means the documented public contracts have a defined compatibility boundary and the audited source passes the listed local and baseline checks. It does not mean v1.0.0 has been released, that all workflows are understood, or that the separate PR/main CI gates may be skipped. The classifier recommendation is Beta. A future Issue #33 may handle only the separately authorized version, changelog, tag, Release, and artifact freeze steps.
