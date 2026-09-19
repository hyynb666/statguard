# StatGuard

StatGuard is an early-stage static analyzer for statistical validity, model
evaluation, and reproducibility risks in Python scripts and Jupyter Notebooks.
The planned analyzer reports conservative, explainable findings based on AST
evidence and data lineage. Submitted code must never be imported or executed.

## Current status

Milestone 1, Issue 1 establishes packaging, the CLI entry point, public data/rule
interfaces, and development tooling. Version `0.1.0.dev0` supports `--help` and
`--version`. Parsing, `statguard check`, text/JSON scan reports, and all statistical
detection rules are **not implemented yet**. No scan results or statistical
guarantees are available in this foundation release.

## Install from this repository

Requires Python 3.11+. CI covers Python 3.11–3.14 on Windows and Linux.
This repository has not been published to PyPI; install from the checkout:

```text
git clone https://github.com/hyynb666/statguard.git
cd statguard
python -m venv .venv
```

Activate it on Windows PowerShell with `.venv\Scripts\Activate.ps1`, or on
Linux/macOS with `source .venv/bin/activate`. If PowerShell activation is
unavailable, use `.venv\Scripts\python.exe` and `.venv\Scripts\statguard.exe`
directly; changing execution policy is not required.

```text
python -m pip install -e ".[dev]"
statguard --help
statguard --version
python -m statguard --version
```

`statguard --version` prints `statguard 0.1.0.dev0`. With no arguments, the CLI
prints help. These commands exit with `0`; unsupported arguments (including
`check`) exit with `2`. The future scan command and its exit codes are specified
in [the PRD](docs/PRD.md), not exposed as a pretend successful scan today.

## Package boundaries

```text
src/statguard/
  cli.py                 # help/version entry point, standard-library argparse
  core/
    findings.py          # immutable Finding and Evidence categories
    rule.py              # Rule[ContextT] protocol
    registry.py          # explicit registration and deterministic iteration
  parsers/               # reserved for Issue 2
  rules/                 # no built-in rules yet
  reporters/             # reserved for text/JSON rendering
tests/
```

`from statguard.core import Evidence, Finding, Rule, RuleRegistry` exposes the
minimal interfaces. Findings carry a path, one-based line/column and optional
one-based code-cell index, observed message, risk, recommendation, and evidence
category. Evidence is not severity, and an undetermined observation is not a
confirmed violation. The future parser must convert AST locations to this public
coordinate convention and disclose notebook document-order limitations.

Rules provide stable `rule_id` and `description` metadata plus
`analyze(context) -> Iterable[Finding]`. Context is generic for now; no analysis
context or engine is implemented. The registry rejects duplicate IDs, supports
lookup, and iterates by ID without executing rules or importing plugins. These
interfaces remain provisional during pre-alpha development.

## Development

```text
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m build
```

The build produces an sdist and wheel under `dist/`. CI tests an installed package
and verifies a wheel in an isolated environment. See [CONTRIBUTING.md](CONTRIBUTING.md)
and [AGENTS.md](AGENTS.md) for the workflow; [docs/PRD.md](docs/PRD.md) defines the
product scope and rule acceptance criteria.

## License

StatGuard is available under the [MIT License](LICENSE).
