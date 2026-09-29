# Changelog

Changes to StatGuard are documented here. This project follows the spirit of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- GitHub composite Action integration for configurable CI scans, report output,
  failure thresholds, rule disabling, and path exclusions.

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
