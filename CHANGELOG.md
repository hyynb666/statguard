# Changelog

Changes to StatGuard are documented here. This project follows the spirit of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Explicit inline Finding suppression with rule-specific `statguard: ignore`
  and `statguard: ignore-next-line` comments for Python files and Notebook code
  cells.
- Expanded the offline HTML report into a dashboard with richer overview
  metrics, rule/severity distributions, file/confidence filters, broader search,
  and bulk Finding controls.
- Added ML007 for supported GridSearchCV/RandomizedSearchCV fits that consume
  proven held-out split data; unresolved patterns remain outside its scope.

## [0.2.0] - 2026-09-30

### Added

- Project policy from `[tool.statguard]` in `pyproject.toml`, with explicit
  config selection and a config-discovery opt-out in the CLI and GitHub Action.
- GitHub composite Action integration for configurable CI scans, report output,
  failure thresholds, rule disabling, and path exclusions.
- SARIF 2.1.0 reporting for CLI and GitHub Action output, with Code Scanning
  integration guidance. The Action generates reports but does not upload them.

## [0.1.0] - 2026-09-29

### Added

- Static scanning for Python files and Jupyter Notebook code cells.
- Conservative import resolution, binding-aware provenance, and the v0.1 core
  rules ML001–ML006 and ST001–ST002.
- Additional ML009 cross-validation preprocessing rule.
- Console, JSON, and offline interactive HTML reports; recursive directory
  scanning and CLI controls.
- Python packaging, Windows/Linux CI, and no-execution safety coverage.

### Security

- Submitted Python and Notebook code is parsed, never executed by default.
- Notebook outputs are not analyzed. HTML findings are escaped and the local
  report script is constrained by a Content Security Policy.

### Known limitations

- Rule coverage is limited to documented, statically resolvable patterns.
- Notebook cells are independent; document order does not prove historical
  execution order, and cross-cell data flow is not modeled.
- A clean scan does not establish statistical correctness. See the individual
  rule guides and [release audit](docs/release-audit-v0.1.md).
