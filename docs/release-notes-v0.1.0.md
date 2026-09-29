# StatGuard v0.1.0

Initial Alpha release of StatGuard. This release is distributed through GitHub;
it is not published to PyPI.

## Highlights

- Conservative static analysis for Python and Jupyter Notebook statistical and
  machine-learning workflows.
- Eight v0.1 core rules and the additional ML009 cross-validation preprocessing
  rule.
- Console, JSON, and offline interactive HTML reports, including filtering,
  search, and expandable finding details.
- Python source is analyzed statically without executing submitted code.

## Rules

The eight v0.1 core rules are ML001–ML006 and ST001–ST002. ML009 is an
additional rule and is not counted as a core rule.

## Safety

- Python source and Notebook cells are parsed, never executed.
- Stored Notebook outputs are not analyzed.
- HTML report content is escaped, with a restrictive Content Security Policy
  and no remote resources.

## Known limitations

- Coverage is limited to documented patterns that can be resolved statically.
- Unresolved dynamic behavior is left undetermined or skipped.
- Cross-file and cross-Notebook-cell data flow are not analyzed.
- Notebook document order does not establish historical execution order.
- A clean scan does not prove statistical correctness.

## Installation

StatGuard v0.1.0 is available from the GitHub source and release artifacts. It
is not published to PyPI. Clone the release tag with:

```text
git clone --branch v0.1.0 --depth 1 https://github.com/hyynb666/statguard.git
cd statguard
python -m pip install .
```

Alternatively, install the wheel attached to this GitHub Release.
