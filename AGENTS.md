# StatGuard Engineering Guidelines

These instructions apply to the StatGuard repository. `docs/PRD.md` is the product source of truth for v0.1 scope, rule acceptance criteria, CLI behavior, and release requirements. Read the relevant PRD sections before changing behavior. Do not silently weaken a requirement; document any proposed change and obtain review.

## Product scope and statistical accuracy

- StatGuard is a static analyzer for Python 3.11+ `.py` files and Python code cells in `.ipynb` files. The v0.1 rules are ML001–ML006 and ST001–ST002. Later candidates in PRD Section 6 are not v0.1 acceptance gates.
- Prefer defensible findings to broad pattern matching. A shared file, coincident API names, or suggestive variable names such as `X_test` are not proof of data lineage, call order, or statistical harm.
- Require a local AST pattern and, where a rule depends on it, traceable assignments, aliases, data lineage, and ordering. For ML001–ML003, prove that the fitted preprocessing input is in the lineage subsequently split into held-out data and that fitting precedes the split. Unrelated data or safe train-only fitting must not trigger these rules.
- For ML004, require proven test-output provenance. For ML005 and ST001, limit absence claims to the analyzed scope; external helpers, dynamic behavior, partial notebooks, and unknown cardinality can make the result undetermined. For ML006, distinguish omitted or `None` seeds from known seeds, unknown expressions, and `shuffle=False`. For ST002, distinguish discarded test results from consumed results.
- Use the PRD evidence categories consistently: confirmed code pattern, potential statistical risk, general analysis advice, and undetermined. Describe what the source establishes and what remains unknown. An undetermined state must never be reported as a confirmed violation. Abstain from a rule finding when its required evidence cannot be established; a scan notice may explain reduced coverage.
- Every finding must identify its rule, actionable location, observed pattern, statistical risk, recommended action, and evidence category. Keep rule IDs stable and wording accurate; do not claim measured model performance or statistical significance from static source analysis.

## Static analysis safety and input handling

- Treat analyzed source and notebooks as untrusted input. Never import a target module, execute a script or notebook cell, evaluate a target expression, or invoke target code to discover behavior. Do not rely on stored notebook outputs.
- Parse Python with `ast`. Read notebooks as data, analyze Python code cells in document order, and report one-based code-cell and in-cell line locations. Document that document order is not proof of historical execution order.
- Handle malformed files, unsupported syntax, non-Python cells, notebook magics, and unresolved dynamic behavior with clear scan errors or notices at useful locations. Do not turn parse or coverage failures into statistical findings. Continue scanning other inputs where possible.
- Directory traversal and emitted results must be deterministic. Avoid loading notebook outputs into analysis. Keep JSON stdout valid standalone JSON; send any non-JSON diagnostics elsewhere.

## Architecture and compatibility

- Use Python 3.11+, `pyproject.toml`, and a `src/statguard/` package layout. Keep Parser, Analysis Context, Finding, Rule Registry, Rule Engine, and Reporters separate as described in PRD Sections 3 and 7.
- Parser owns AST units and locations. Analysis Context owns conservative import/call resolution, assignments, aliases, ordering, and lineage. Rules consume context and emit Findings through the registry and engine; rules do not print. Text and JSON reporters render the same Finding model.
- Keep the public `statguard check <path>` interface and `--format json` behavior aligned with the PRD. Exit status is `0` for a completed scan without findings, `1` for a completed scan with findings, and `2` for invalid invocation or any scan error. An undetermined notice alone is not a finding.
- Findings must be deduplicated and sorted by path, cell, line, column, and rule ID. JSON includes a documented schema version, scanned-file summary, findings, and scan errors/notices. Review and document compatibility impact before changing rule IDs, JSON schema, or exit behavior.
- Minimize dependencies and keep supported library-call patterns explicit in rule documentation. Unsupported or dynamically resolved APIs are limitations, not evidence of safety.

## Tests and quality gates

- Use `pytest` for unit and CLI integration tests and Ruff for linting. Run both before requesting review; CI should cover supported Python versions including 3.11.
- Every rule change needs positive, negative, and boundary fixtures, plus a known-limitations note. Assert rule ID, evidence category, actionable location, and the absence of false positives. Add a regression fixture for each confirmed false positive or false negative.
- Test ML001–ML003 with shared lineage, fit-before-split order, unrelated calls, and safe train-only fitting. Test bounded and uncertain cases for ML005 and ST001. Follow the rule-specific acceptance cases in PRD Section 5 for all eight rules.
- Integration tests must cover `.py`, `.ipynb`, and directory scans; deterministic ordering; text/JSON parity; JSON parseability; exit codes; and graceful parse errors. Include a side-effect fixture proving that scanning does not execute submitted code.
- Do not treat passing tests as a substitute for reviewing statistical reasoning and the precise evidence used by each finding.

## Development workflow

1. Read the relevant PRD rule, architecture, and acceptance sections. State the evidence required and the cases where the analyzer must abstain.
2. Make a focused change within the component that owns the behavior. Keep parsing, context building, rule decisions, and reporting independent.
3. Add or update rule documentation and the smallest meaningful set of positive, negative, boundary, safety, or regression tests.
4. Run focused tests during development, then the full pytest suite and Ruff before review. Inspect text and JSON diagnostics for location, wording, category, and deterministic order.
5. Review the diff for accidental PRD or generated-file changes. Record limitations, compatibility decisions, and user-visible CLI or JSON changes in the appropriate documentation.
6. Submit changes for review against the PRD acceptance criteria. Publication, deployment, package upload, and creation of GitHub issues are separate actions and require explicit authorization.
