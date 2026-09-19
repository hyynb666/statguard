# StatGuard Product Requirements Document

**Status:** Initial product requirements  
**Target release:** v0.1 (Milestones 1–4)  
**Audience:** Maintainers, contributors, and users of Python data science code

## 1. Product overview

StatGuard is an open-source static analyzer for Python scripts and Jupyter Notebooks. It helps data scientists and machine learning practitioners identify code patterns that can compromise statistical validity, model evaluation, or reproducibility. A finding identifies the rule, source location, observed pattern, statistical risk, and a concrete next step. StatGuard analyzes source code; it must never execute submitted code by default.

The first release favors defensible findings over broad pattern matching. Merely finding `fit_transform` and `train_test_split` in one file is insufficient evidence of leakage. When data lineage or execution order cannot be established, StatGuard must state the uncertainty or abstain from issuing a rule finding.

### Goals

- Detect the eight v0.1 rules in Section 5 across `.py` and `.ipynb` inputs.
- Produce useful human-readable CLI diagnostics and machine-readable JSON.
- Make every rule explainable, testable, and conservative about uncertain data flow.
- Provide an installable, documented Python package suitable for public GitHub collaboration.

### Out of scope for v0.1

Web UI, database, LLM API, VS Code plugin, R support, executing notebooks or scripts, dynamic analysis, and claims about actual model performance or statistical significance. Later ideas in Section 6 are not v0.1 release gates.

## 2. Users and usage scenarios

| User | Scenario | Expected result |
| --- | --- | --- |
| Data scientist | Run `statguard check analysis.py` before sharing an analysis | Location-specific findings with statistical rationale and repair guidance. |
| Notebook author | Run `statguard check experiment.ipynb` before publishing results | Findings refer to notebook cell and line, while uncertain execution order is disclosed. |
| ML engineer | Run `statguard check ./project` during review or CI | Deterministic scan of supported files, an actionable exit status, and optional JSON output. |
| Contributor | Add or revise a rule | A registered rule with documented evidence requirements, positive, negative, and boundary tests. |

The intended installation and basic interface are:

```text
pip install statguard
statguard check analysis.py
statguard check experiment.ipynb
statguard check ./project
statguard check ./project --format json
```

## 3. Scope and functional requirements

### 3.1 Input and parsing

- Support Python 3.11+ source syntax in `.py` files and Python code cells in `.ipynb` files. Accept a file or a directory; directory scans recursively discover supported files in a deterministic order.
- Read notebook JSON without running cells or trusting stored outputs. Report notebook locations as a one-based code-cell index and a one-based line within that cell, as well as the file path. Analyze cells in document order only; do not claim this is the historical execution order.
- Use Python `ast` for core source parsing and analysis. Parsing failures, unsupported syntax, non-Python cells, and notebook magics must yield a clear scan notice or error at the affected location; they must not become fabricated statistical findings. Other files continue scanning where possible.

### 3.2 Analysis and findings

- Separate Parser, Analysis Context, Rule Engine, Finding, Rule Registry, and Reporter components. The Parser produces ASTs and source locations. Analysis Context tracks resolved imports/calls, assignments, conservative aliases, call order, and data lineage. The Rule Registry declares metadata and enables rule discovery. The Rule Engine evaluates registered rules against context and emits Findings. Reporters render text and JSON from the same Finding model.
- Track only relationships supported by AST evidence. At minimum, the v0.1 data-flow layer must connect assignments and simple aliases to preprocessor fitting, `train_test_split` outputs, model fitting, and evaluation calls. Unknown dynamic calls, mutations, branches, interprocedural behavior, and notebook re-execution must not be silently assumed to be safe or unsafe.
- Each finding contains a stable rule ID; path; line and column, plus cell for notebooks; concise observed-pattern description; risk explanation; recommended action; and evidence classification. Optional related locations may show the split, fit, or evaluation that establishes the relationship.
- Use these evidence classifications consistently: **confirmed code pattern** (the reported relationship is established in analyzed code), **potential statistical risk** (the pattern is observed but its real-world harm depends on unknown context), **general analysis advice** (a low-certainty recommendation that must not masquerade as an error), and **undetermined** (static evidence is insufficient to judge). The category describes evidence, not a claim that the analysis outcome is statistically invalid. An undetermined state may be represented as a scan notice or omitted rule finding, but never as a confirmed violation.
- Deduplicate identical findings and order output by path, cell, line, column, and rule ID. Findings must be reproducible for identical inputs.

### 3.3 CLI and reporting

- Provide `statguard check <path>` with default text output and `--format json`. Text output must make the location, rule ID, evidence category, risk, and fix discoverable without reading source code.
- JSON output must be valid standalone JSON on stdout and expose a documented schema version, scanned-file summary, findings, and scan errors/notices. Diagnostics or progress must not corrupt JSON stdout.
- Exit with `0` when a scan completes without findings, `1` when it completes with findings, and `2` for invalid invocation or any scan error. Document this behavior for CI users. An undetermined notice alone does not count as a finding.

## 4. Statistical correctness policy

1. Rules must cite a local AST pattern and, where the rule depends on it, proven variable lineage and call order. Names such as `X_test` may support a hypothesis but cannot alone prove provenance.
2. A fitted transformer is a leakage concern only when its input is shown to include observations subsequently used as held-out data. Unrelated transformer and split calls must not trigger ML001–ML003.
3. A rule may report potential risk when the observed code is real but the statistical consequence depends on facts unavailable to static analysis. Its wording must say what is unknown.
4. Absence claims are bounded to a traceable analysis scope. They must not treat unscanned files, dynamic calls, notebook execution history, or unsupported libraries as proof that a validation or correction step never occurred.
5. Every v0.1 rule requires documented positive and negative examples, boundary cases, and known limitations. Tests must check both the finding and its absence, including evidence category and location.
6. When a rule cannot establish its required relationship, abstain from the finding. A scan notice can explain incomplete coverage without inflating rule counts.

## 5. v0.1 detection rules and acceptance requirements

Examples below describe typical cases. Exact variable names are illustrative; implementations must use resolved calls and data flow rather than these spellings alone. The initial supported library patterns should be documented per rule, starting with common scikit-learn and SciPy/statsmodels APIs. Unsupported or dynamically resolved APIs are a known limitation, not evidence of safety.

### ML001 — Pre-split scaler fit

**Trigger:** A known scaler's `fit` or `fit_transform` consumes `X`, then the resulting same-lineage data is passed to `train_test_split` and yields held-out data. Report the fit location and related split location. The observed sequence is confirmed; leakage is a potential statistical risk because the effect depends on the preprocessing and data.

**Do not trigger:** `train_test_split(X, y)` occurs first and the scaler fits only `X_train`; or an unrelated dataset is scaled before a different dataset is split. **Boundary:** Aliases must preserve the relationship; an unknown wrapper or branch with no provable ordering must lead to abstention. **Acceptance:** Positive, negative, alias/order, and unknown-lineage tests pass; a file merely containing both API names produces no ML001.

### ML002 — Pre-split imputer fit

**Trigger:** A known missing-value imputer fits on data later split into training and held-out portions. Report the imputer fit and split as in ML001.

**Do not trigger:** An imputer fits only on the training portion after the split, then transforms the test portion; or it fits a separate dataset. **Boundary:** A custom imputation helper with unresolved behavior is undetermined. **Acceptance:** Test direct `fit` and `fit_transform`, safe train-only fitting, unrelated data, and unresolved helper behavior.

### ML003 — Pre-split feature selection

**Trigger:** A known feature selector fits on data before that same lineage is split into training and held-out portions, including `fit_transform` followed by a split.

**Do not trigger:** The selector fits on `X_train` after the split and only transforms `X_test`; or the selector is applied to unrelated data. **Boundary:** A selector inside a training-only pipeline must not be mistaken for a pre-split fit. **Acceptance:** Cover direct selection, safe train-only use, an unrelated split, and a pipeline/unknown-call boundary.

### ML004 — Fit on an explicit test set

**Trigger:** A recognized model's `fit` receives features or labels traceably produced as test outputs by `train_test_split`. Report the model fit as a confirmed code pattern and explain why training on held-out data undermines evaluation.

**Do not trigger:** `fit(X_train, y_train)` followed by `predict(X_test)` or `score(X_test, y_test)`. **Boundary:** A variable named `test_data` with no proven split provenance does not suffice; a simple alias of `X_test` does. **Acceptance:** Tests verify feature and target provenance, safe evaluation, aliasing, and misleading names.

### ML005 — Training-only evaluation

**Trigger:** Within a traceable model workflow, a recognized estimator is fitted on training data and its evaluation uses only that same training lineage, with no independent validation/test evaluation observed in the bounded scope. Classify as a potential statistical risk, not proof that independent evaluation never occurred.

**Do not trigger:** The same model is also evaluated on a traceably separate validation or test set in the scope, or no evaluation call can be resolved. **Boundary:** A partial file/notebook, external evaluation helper, or ambiguous model alias cannot justify an absence claim; abstain or mark coverage undetermined. **Acceptance:** Tests cover training-only `score` or metric evaluation, validation evaluation, ambiguous helper, and an unrelated model's evaluation.

### ML006 — Random split without a fixed seed

**Trigger:** A resolved random `train_test_split` call omits `random_state` or explicitly passes `None`. Report a confirmed code pattern with a potential reproducibility risk.

**Do not trigger:** A concrete literal seed or traceable non-`None` seed is supplied. **Boundary:** An unknown `random_state` expression is undetermined; deterministic splitting explicitly configured with `shuffle=False` must not be reported. **Acceptance:** Cover omitted/`None`, fixed seed, unknown expression, and non-shuffled split.

### ST001 — Repeated tests in a loop without observed correction

**Trigger:** A resolved hypothesis-test call is executed in a loop and multiple tests are possible, while no recognized multiplicity-correction step is observed in the traceable result flow or bounded analysis scope. State that the code shows repeated testing but correction may occur elsewhere; classify as a potential statistical risk.

**Do not trigger:** The p-values are collected and passed to a recognized correction function, or the loop is provably single-iteration. **Boundary:** Dynamic loop cardinality or correction in an unresolved helper makes the correction status undetermined; the diagnostic must not claim correction is absent globally. **Acceptance:** Cover an uncorrected loop, corrected loop, single iteration, and unknown helper/cardinality cases.

### ST002 — Discarded statistical test result

**Trigger:** A resolved statistical test call is a bare expression statement, or its result is assigned to `_`, so the result is not retained or otherwise consumed. Report the confirmed code pattern and advise recording or inspecting the result.

**Do not trigger:** The result is assigned, returned, passed to another function, printed, or explicitly recorded. **Boundary:** A call whose identity cannot be resolved as a test is undetermined; assignment to `_` is still a deliberate discard and should trigger with wording that acknowledges intent. **Acceptance:** Cover a bare call, `_` assignment, assignment/return/logging, and an unrelated function call.

## 6. Later-version candidates

The following rules are candidates after v0.1 feedback and evidence-quality review. Their IDs are reserved here but they are not implemented or counted in v0.1 acceptance: **ML007** test data used for model selection; **ML008** preprocessing fitted separately on train and test sets; **ST003** multiple pairwise tests after ANOVA without observed correction; **ST004** possible paired-test selection issue; **ST005** missing samples dropped immediately before inference; **ST006** incorrect interpretation of a p-value; **ST007** possible variable-scale issue in Pearson correlation. Later delivery may also include a GitHub Action integration, HTML report, or IDE integration. Each requires its own feasibility review, evidence rules, limitations, and tests before becoming a release commitment.

## 7. Architecture and implementation constraints

Use Python 3.11+, `pyproject.toml`, and a `src/` layout. A proposed package boundary is:

```text
src/statguard/
  cli.py
  parser.py
  context.py
  findings.py
  registry.py
  engine.py
  reporters/
  rules/
tests/
docs/
```

The Parser returns per-file or per-cell AST units and locations. Analysis Context builds conservative symbol, alias, order, and lineage facts. Registered rules consume those facts and emit Findings; they do not print directly. Reporters serialize findings and scan notices. This boundary allows rules to evolve without changing the CLI or output model. The analyzer must not import target modules as a way to inspect them, run notebook cells, evaluate expressions, or invoke user code.

Dependencies should be limited to what parsing, CLI, and reporting require. The public package exposes a `statguard` console script. Rule identifiers and JSON schema changes need documented compatibility decisions.

## 8. Non-functional requirements

- **Safety:** No user-code execution by default; treat source and notebook content as untrusted input. Fail cleanly on malformed files.
- **Precision:** False-positive prevention is a release gate for the explicit negative examples. No rule may infer a data relationship solely from coincident API names.
- **Clarity:** Each finding explains observed evidence, possible consequence, and a practical change. Uncertainty must be visible in wording and category.
- **Reproducibility:** Stable ordering and deterministic output for the same inputs and configuration.
- **Usability:** File and notebook locations are actionable; text and JSON convey equivalent finding content.
- **Maintainability:** Rules are independently registered, documented, and tested; public contributions follow a documented workflow.
- **Performance:** The tool should handle ordinary projects without executing code or loading notebook outputs into analysis. Measure representative scans before setting numerical performance targets.

## 9. Test and release acceptance

- Use `pytest` for unit and CLI integration tests and Ruff for linting. GitHub Actions runs tests and lint on supported Python versions, including 3.11.
- Every v0.1 rule has at least one positive, one negative, and one boundary fixture, plus a written known-limitation note. ML001–ML003 additionally prove shared lineage and fit-before-split order. ML005 and ST001 verify that bounded absence claims are worded as risks.
- Integration tests scan a `.py` file, an `.ipynb` file, and a directory; verify locations, deterministic ordering, text/JSON parity, JSON parseability, exit codes, and graceful parse errors.
- A safety test uses a source file or notebook cell with a side effect and verifies scanning does not execute it. Regression tests cover every confirmed false positive or false negative fixed before release.
- v0.1 is acceptable when all eight rules meet their stated cases, CLI and JSON meet Section 3, tests and Ruff pass in CI, and installation via the documented `pip install statguard` path works from the published package. Public release also requires the items in Section 10.

## 10. GitHub open-source release requirements

Before publishing, provide a README with installation, CLI examples, sample diagnostics, supported patterns, limitations, and a clear statement that source is not executed. Choose and include an open-source license, `CONTRIBUTING.md`, a code of conduct, issue and pull request templates, and a security reporting path. Document rule IDs, evidence categories, JSON schema, exit codes, and notebook-order limitations. Configure `pyproject.toml` package metadata and console entry point, publish a versioned release and changelog, and ensure GitHub Actions validates the release commit. Package publication and any PyPI credentials are separate release operations; this PRD does not authorize them.

## 11. Development roadmap and GitHub issue plan

Each row below is intended as a separate GitHub Issue with a reviewable deliverable. Complete the listed acceptance condition before closing it. The rows are an issue plan, not authorization to create issues during this documentation task.

| Milestone | Issue | Acceptance condition |
| --- | --- | --- |
| M1 — foundation | Initialize `src/` package, `pyproject.toml`, Ruff and pytest | Package installs locally; `statguard` entry point and lint/test commands work. |
| M1 — foundation | Implement Python and notebook Parser | AST units and actionable locations are produced; parse failures are surfaced; input is never executed. |
| M1 — foundation | Define Finding, Rule Registry, Rule Engine, and basic text CLI | A fixture rule runs through `statguard check` and yields a stable, located diagnostic. |
| M1 — foundation | Establish foundational tests | Parser, CLI, malformed input, and no-execution tests pass. |
| M2 — ML analysis | Implement conservative Analysis Context and lineage tracking | Assignment, alias, call order, and split-output fixtures distinguish connected from unrelated data. |
| M2 — ML analysis | Implement ML001–ML003 | Each rule passes positive, negative, boundary, and limitation cases; coincident API names do not trigger. |
| M2 — ML analysis | Implement ML004–ML006 | Test provenance, bounded evaluation, and random-state cases pass with correct evidence categories. |
| M3 — statistical analysis | Implement ST001 | Corrected, uncorrected, single-test, and uncertain-scope fixtures pass. |
| M3 — statistical analysis | Implement ST002 | Discarded, consumed, deliberate-discard, and unresolved-call fixtures pass. |
| M4 — release | Complete CLI and JSON Reporter | Documented schema, deterministic output, notebook locations, and exit codes pass integration tests. |
| M4 — release | Expand regression suite and CI | Pytest and Ruff pass on supported Python versions in GitHub Actions. |
| M4 — release | Complete user and contributor docs plus package metadata | README, rule docs, limitations, license, contribution/security guidance, and installable package are reviewed. |
| M4 — release | Prepare v0.1 public release | Changelog, tagged version, package installation smoke test, and release checklist are complete. |
| M5 — feedback-driven | Triage user reports and prioritize candidate rules/integrations | Each proposed addition has evidence criteria, false-positive review, scoped issue, and acceptance tests before implementation. |

Milestones 1–4 define the first release. Milestone 5 begins only after user feedback and separate prioritization.
