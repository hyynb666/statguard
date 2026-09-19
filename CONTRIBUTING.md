# Contributing to StatGuard

Read [AGENTS.md](AGENTS.md) and [docs/PRD.md](docs/PRD.md) before changing behavior.
The current foundation includes packaging, help/version commands, and minimal
public interfaces. Python/notebook parsing and detection rules belong to later
issues. Agree on a scoped change before expanding the roadmap.

## Set up and validate

Use Python 3.11+ and a virtual environment as described in the README, then run:

```text
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m build
statguard --help
statguard --version
```

Use `python -m ruff format .` to apply formatting before the checks. Tests must
exercise the installed package; do not add the source directory to `PYTHONPATH`
or pytest's import path to hide packaging errors. CI repeats tests and lint on
Windows and Linux with Python 3.11–3.14 and checks a built wheel independently.

## Design and test expectations

- Keep parsing, conservative analysis facts, rule evaluation, registry metadata,
  findings, and reporting separate. Rules return findings and never print them.
- Never import target modules, execute notebook cells, evaluate submitted
  expressions, or invoke target code. Source and notebook content are untrusted.
- Require AST evidence and proven lineage/order when a rule depends on them.
  Coincident API names or variable names cannot establish statistical harm.
- When rule implementation begins, add positive, negative, boundary, and known
  limitation cases for every rule. Add regression tests for confirmed false
  positives/negatives and a no-execution test for parsers/scanning.
- Preserve uncertainty in evidence categories and wording. An undetermined
  observation must not become a confirmed violation or inflate finding counts.
- Keep output deterministic and document compatibility changes to IDs, public
  interfaces, JSON schema, and exit codes. This foundation does not yet define
  or implement a JSON report schema.

## Review workflow

Create a focused branch, implement the smallest complete change, and run the
checks above. In the pull request, describe the behavior, relevant PRD acceptance
criteria, actual test results, and remaining limitations. Do not commit virtual
environments, generated distributions, caches, or credentials. Keep changes to
the product requirements explicit and reviewed.

Set the package version in `pyproject.toml`; CLI and Python package versions are
read from installed distribution metadata. Reinstall after changing that version.
Package publication and release tagging are separate operations and are not part
of a normal development push. Contributions are distributed under the project's
[MIT License](LICENSE).
