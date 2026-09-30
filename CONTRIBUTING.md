# Contributing to StatGuard

Read [AGENTS.md](AGENTS.md) and [docs/PRD.md](docs/PRD.md) before changing behavior.
The foundation includes packaging, CLI scanning, Console/JSON reporting, public
interfaces, Python and Notebook parsing, and Analyzer execution. Built-in rules
ML001–ML006, ML009, ST001 and ST002 are documented in `docs/`. New rule work should follow the evidence,
abstention, testing, and documentation conventions already established there.
The eight v0.1 core rules are ML001–ML006 and ST001–ST002; ML009 is additional.
See the [Code of Conduct](CODE_OF_CONDUCT.md) and [Security Policy](SECURITY.md)
when participating or reporting a vulnerability.

Inline Finding suppression is Analyzer policy, not rule behavior: detection
rules must not read or interpret `statguard: ignore` comments. Changes to the
suppression syntax require false-positive, safety, and Notebook cell-boundary
tests; consult [the suppression contract](docs/suppressions.md).

Project-level CLI policy is intentionally limited to `[tool.statguard]`
`exclude`, `disable-rules`, and `fail-on`; see
[the configuration contract](docs/configuration.md) before changing it.

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

## Pull requests

Open a pull request against `main` and use the repository pull request template.
Link the related issue, describe behavior and evidence changes, and include
positive, negative, and boundary tests. Rule changes must explain statistical
rationale, false-positive boundaries, and abstention behavior. Do not execute
submitted Python or Notebook code during tests or analysis. Wait for CI and
review before merging; do not publish packages or create releases as part of an
ordinary implementation pull request.

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
  interfaces, JSON schema, and exit codes. The schema is documented in
  [docs/reporting.md](docs/reporting.md).

## Parser contributions

Follow [the parser API contract](docs/python-parser.md). Preserve the raw AST and
unknown dynamic expressions; do not resolve imported libraries or introduce rule
logic into syntax parsing. Treat `enclosing_definitions` as syntax ancestry, not
runtime scope or proof of execution order.

Test strings and files, Unicode character columns, multiline spans, source
encodings, explicit failures, and absence of target-code side effects. Simulate
permission-denied reads in tests rather than changing machine permissions.
Notebook support reuses `parse_source` and maps cell identity separately. Follow
[the Notebook contract](docs/notebook-parser.md): test both cell indexes, mixed
cell types, partial parse errors, magic/shell syntax, language metadata, and
ignored outputs. Existing core interfaces remain unchanged.

## Core interface contributions

Follow [the core interface contract](docs/core-interfaces.md). Keep Evidence
separate from severity and confidence. Preserve Finding's legacy field names and
constructor order, and distinguish the original Notebook cell index from the
code-cell ordinal. Use fixture rules to test check/metadata and registry selection
without mixing statistical decisions into the core interfaces. Cover invalid metadata,
duplicate IDs, deterministic selection, enable/disable behavior, and analyze-only
rule compatibility. Registration must not execute the rule's detection method.

## Analyzer contributions

Follow [the Analyzer contract](docs/analyzer.md). Keep AnalysisContext scoped to
one parsed source unit and expose parser-owned AST/indexes without evaluating
source or Notebook output data. Use test-only fixture rules to verify enabled
selection, location mapping, exact deduplication, parser failures, rule failures,
and partial Notebook results. New rules must report their own evidence precisely;
Analyzer cannot infer statistical harm or repair an unsupported cell.

## Symbol resolution contributions

Follow [the symbol contract](docs/symbols.md). Preserve point-of-use binding
versions, parser-owned AST identity and independent function/cell scopes.
Never infer types from capitalization or library identity from coincident names.
Test alias shadowing, reassignment, control-flow barriers, dynamic operations
and unknown origins; recorded calls do not establish input/output lineage.

## Scanner and reporter contributions

Follow the [report contract](docs/reporting.md) and [HTML report safety guide](docs/html-report.md).
Preserve stable traversal and
complete, partial, and failed statuses. Keep JSON stdout standalone and never
serialize AST, source, Notebook outputs, or arbitrary rule exception text.
Test file/Notebook/directory scans, exclusions, empty inputs, explicit errors,
exit codes, output writes, HTML escaping, and no-execution behavior with test-only
rules. HTML dynamic content must always be escaped; interactive scripts must
be fixed code pinned by a CSP hash and must not interpolate report content.
Keep HTML output deterministic, self-contained, readable without JavaScript,
and free of source snippets, remote resources, browser storage, and Notebook
outputs. Escape dynamic text and attributes; update the CSP hash whenever the
fixed script changes. See the [HTML report guide](docs/html-report.md).
Review any proposed JSON schema or exit-code change before release.

SARIF additions should follow [the SARIF contract](docs/sarif.md): keep it a
separate format from JSON schema 1.0, preserve Notebook cell coordinates as
metadata rather than raw JSON regions, and never upload from the StatGuard
Action. Test rule metadata ownership, stable fingerprints, invocation errors,
Windows paths, report-before-threshold behavior, and no execution of inputs.

## GitHub Action contributions

The root composite Action is documented in [docs/github-action.md](docs/github-action.md).
Keep Action inputs out of shell command strings: the Python runner must build
an argument list and invoke StatGuard without a shell. The package must be
installed from `GITHUB_ACTION_PATH`, while the analyzed repository is rooted
at `GITHUB_WORKSPACE`. Run the Action smoke workflow on both Linux and Windows
when changing its metadata, runner, or input handling.

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

## Release preparation

The v0.1.0 audit and checklist are historical records. For v0.2.0, use the
[v0.2 release audit](docs/release-audit-v0.2.md) and
[v0.2 release checklist](docs/release-checklist-v0.2.md). Release operations
must follow their version, artifact, and no-PyPI boundaries.

## Provenance contributions

Follow [the provenance contract](docs/provenance.md). Keep syntactic call inputs
separate from proven data sources. Library return semantics belong in the small
adapter, with official documentation and negative cases for coincident names,
reassignment, unknown effects and ambiguous argument/output shapes. Never infer
train/test roles from variable spelling or generic method names.

## ML001 changes

Follow [the ML001 contract](docs/ml001.md). Preserve exact receiver provenance,
input lineage and same-scope evaluation order. Test safe train-only fitting,
unrelated inputs, alias/rebinding, unknown state and configuration that disables
learning. Medium confidence describes static risk, not measured model harm.

## ML002 changes

Follow [the ML002 contract](docs/ml002.md). Require an exact sklearn imputer
construction, proven fit_transform output lineage and same-scope order. Preserve
the distinction between data-dependent SimpleImputer strategies, fixed constant
replacement, KNN reference samples and Iterative fitted models. Dynamic strategy
semantics must cause conservative abstention.

## ML003 changes

Follow [the ML003 contract](docs/ml003.md). Require an exact supported sklearn
feature-selector construction, proven fit_transform output lineage, and
same-scope order. Supervised selector findings need a known score function and
an explicit target; VarianceThreshold must remain described as an unsupervised
variance operation. Unknown scoring semantics require abstention.

## ML004 changes

Follow the [ML004 contract](docs/ml004.md). Require an explicit supported
sklearn estimator construction, the same receiver at `.fit`, and proven test
roles for its actual feature and/or label input. Do not treat `predict`,
`predict_proba`, `decision_function`, `score`, `transform`, or `partial_fit` as
supported fitting evidence. Add negative fixtures for misleading names,
custom estimators, train-only fitting, and unresolved scope or lineage. Findings
describe potential risk without claiming a measured effect.

## ML005 changes

Follow the [ML005 contract](docs/ml005.md). Require an exact supported
estimator, train/test roles from the same `train_test_split`, a train-role fit,
and a training-role `.score()` call for the same fit episode. Decide only after
the bounded scope is scanned so a corresponding held-out score can suppress
the candidate. Training score is useful in many workflows and is not itself an
error. Do not infer absence outside the analyzed scope or count a different
model, split, Notebook cell, metric helper, or cross-validation clone as a
matching held-out score.

## ML006 changes

Follow the [ML006 contract](docs/ml006.md). Require a resolved sklearn
`train_test_split` call. Report only when shuffling is explicitly or by default
enabled and `random_state` is omitted or statically `None`; known integer seeds
and `shuffle=False` are safe for this rule. Unknown keyword expansions or
dynamic settings must abstain. This is an informational reproducibility prompt,
not a correctness error.

## ML009 changes

Follow the [ML009 contract](docs/ml009.md). Require a resolved supported
sklearn cross-validation API and a proven fitted-transform output reaching its
`X` argument in the same scope and source order. Reuse component configuration
semantics and `ProvenanceTracker.fitted_transforms` evidence for separate
`fit`/`transform`; do not infer behavior through wrappers or inspect Pipeline
internals. Test aliases, rebindings, CV call identity, fold-local Pipeline use,
component semantics, Notebook locations, outputs and no-execution behavior.

## ST001 changes

Follow the [ST001 contract](docs/st001.md). Require an explicit supported
`scipy.stats` binding, a p-value derived from its result, and a literal
significance-threshold comparison inside a potentially repeated `for` loop.
Do not infer test identity from names, treat separate calls as a hypothesis
family by themselves, or claim that a particular correction is always
required. Keep correction evidence tied to the decisions actually made.

## ST002 changes

Follow the [ST002 contract](docs/st002.md). Report only an exact supported
`scipy.stats` call that is a standalone expression or whose complete result is
assigned to `_`. Partial tuple discards, ordinary assignments, returns,
consumers, attributes, and subscripts are not discarded-result findings.
Resolve the call at its use site; do not infer test identity from its name.
Treat `_` as potentially intentional and avoid framing the observation as a
defect.
