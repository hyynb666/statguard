# Inline Finding suppression

Inline suppression is a v1 compatibility-managed capability for Python source
and Notebook Python code cells. It filters selected Findings after rules run;
it does not alter rule logic, prove a risk harmless, or suppress parser/rule
errors and Notebook notices.

## Syntax and line semantics

Use one or more explicit, case-sensitive Rule IDs in a Python comment:

```python
value = transform(data)  # statguard: ignore ML001
# statguard: ignore-next-line ML001, CUSTOM-01
next_statement()
```

`ignore` applies only to Findings whose reported physical line is the comment
line. `ignore-next-line` applies only to the immediately following physical
line; blank and comment lines count. It does not seek the next statement.
Multiple IDs may be comma-separated. IDs are matched exactly, so custom
registered rules work without a built-in registry lookup.

The directive must occupy the entire comment after its directive text. The
parser recognizes lowercase `statguard`, `ignore`, and `ignore-next-line` and
uses Python's standard-library `tokenize` module to inspect COMMENT tokens.
Text in string literals, docstrings, Markdown/raw Notebook cells, output data,
and ordinary prose is not a directive. Malformed directives, wildcard or
`ALL` requests, and unknown IDs are no-ops; they do not create scan errors.
There is no file-wide, block, severity, wildcard, or configuration-based
suppression.

## Analyzer, reports, and Notebook boundary

Analyzer builds one immutable suppression index per successfully parsed source
unit. Rule results must first pass the existing Finding identity/type checks;
Notebook cell coordinates are normalized before the exact line/Rule ID lookup.
Filtering precedes deduplication and sorting. A rule failure, invalid rule
result, parse failure, or Notebook notice remains visible and continues to
affect scan status and exit code.

Console, JSON, HTML, and SARIF reporters receive the same filtered Finding
collection. Summary counts and `--fail-on` thresholds use it as well. Finding,
AnalysisResult, JSON schema 1.0, and SARIF 2.1.0 are unchanged. No new project
configuration or GitHub Action input is introduced.

Notebook cells are analyzed independently. A comment can suppress only a
Finding in that same Python code cell; it cannot suppress across cells. Cell
document order does not imply historical execution order. Stored outputs are
not analyzed. The syntax layer reads source text only and never executes user
code.

## Example

```python
scaled = scaler.fit_transform(X)  # statguard: ignore ML001
train, test = train_test_split(scaled)
```

The rule still analyzes the code and may produce its normal Finding internally;
Analyzer omits that Finding from final results because the exact rule and line
were explicitly suppressed. Removing the comment restores the unchanged rule
result.
