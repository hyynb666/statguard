# Notebook parser

`NotebookParser` is a source adapter around `PythonSourceParser`. It uses only
the standard library, keeps existing Python/core interfaces unchanged, and does
not detect statistical problems. Public types are exported by `statguard.parsers`.

## Entry points

- `NotebookParser(python_parser=None)` optionally accepts a PythonSourceParser
  instance; every supported code cell delegates to its `parse_source` method.
- `parse_file(path: str | PathLike[str]) -> ParsedNotebook` reads UTF-8 JSON
  (an optional UTF-8 BOM is accepted). The `.ipynb` suffix is case-insensitive.
- `parse_json(text: str, *, path: str = "<notebook>") -> ParsedNotebook` reads
  JSON text without file access. `path` is only a diagnostic label. A non-string
  argument is API misuse and raises TypeError.

The supported container is nbformat 4: a root object with integer `nbformat`,
nonnegative integer `nbformat_minor`, object `metadata`, and array `cells`.
Each cell requires a supported `cell_type`, object `metadata`, and `source` as
a string or a list of strings. Lists are joined with no added separators.
Code cells are parsed; markdown/raw cells are validated but not analyzed.
This follows the [Notebook format](https://nbformat.readthedocs.io/en/latest/format_description.html).

Validation covers the source-bearing structure, not the full nbformat schema:
cell IDs, output schemas, execution counts, attachments, and other optional
metadata are not validated. Unknown cell types and other format major versions
are rejected explicitly.

## Language policy

For a notebook containing code cells, `metadata.language_info.name` or
`metadata.kernelspec.language` must explicitly name `python` or `python3`
(case-insensitive, surrounding whitespace ignored). If both are present, both
must declare Python. Kernel names alone are not evidence of language. Missing
language declarations produce UNKNOWN_LANGUAGE; non-Python or conflicting
declarations produce UNSUPPORTED_LANGUAGE. Malformed metadata is INVALID_NOTEBOOK.
Empty notebooks and notebooks with only markdown/raw cells need no language
declaration, but an explicitly unsupported language is still rejected.

## Results and locations

`ParsedNotebook` contains `path`, `cell_count` (all cells), `code_cells`, and
`notices`. Its `errors` property collects cell errors; `is_complete` means every
code cell parsed, including the vacuous case of no code cells. It does not mean
that execution or statistical analysis would be correct.

Each `NotebookCell` contains:

| Field | Meaning |
| --- | --- |
| `cell_index` | One-based position among all original cells. |
| `code_cell_index` | One-based position among code cells only; use this for the PRD's future `Finding.cell`. |
| `source` | Original cell text, retained even on failure. |
| `parsed` | Existing ParsedSource on success, otherwise None. |
| `error` | NotebookIssue on failure, otherwise None. |

Exactly one of `parsed` and `error` is present. The Python AST, imports,
assignments, calls, arguments, definitions, and unknown dynamic callees remain
available through `parsed`. AST locations are not rewritten. Public source
locations are one-based cell-relative lines and Unicode character columns;
end positions are exclusive. See [Python locations](python-parser.md#locations).

For markdown, code, raw, code, the code cells have index pairs `(2, 1)` and
`(4, 2)`. Cell identity stays on the enclosing NotebookCell; ParsedSource,
Finding, Rule, and RuleRegistry retain their existing interfaces.

Every result includes a DOCUMENT_ORDER notice. Cells are parsed independently
in document order, without consulting execution counts. This is not proof of
historical execution order and establishes no cross-cell variable lineage.

## Failures and unsupported syntax

Fatal file/JSON/structure/language failures raise `NotebookParseError` with an
`.issue` attribute. NotebookIssue has `code`, `path`, `message`, optional
`cell_index`, `code_cell_index`, `line`, and `column`. Missing positions are None.
INVALID_JSON line/column refer to the JSON document. Cell error positions refer
to source within that cell. Diagnostics are errors/notices, never Findings.

Notebook-specific codes are INVALID_JSON, INVALID_NOTEBOOK, UNSUPPORTED_VERSION,
UNSUPPORTED_LANGUAGE, UNKNOWN_LANGUAGE, UNSUPPORTED_SYNTAX, and DOCUMENT_ORDER.
File reads, decoding, Python syntax, and recursion failures reuse existing
ParseErrorCode values (READ_ERROR, ENCODING_ERROR, UNSUPPORTED_FILE,
SYNTAX_ERROR, RESOURCE_LIMIT).

Python failures are retained per cell and parsing continues with later cells.
Consumers must inspect `errors` or `is_complete`; iterating only successful units
would lose coverage information. A failed cell never receives a partial AST.

Standard Python parsing takes precedence. After a syntax failure, tokenization
recognizes common explicit IPython markers: `%`/`%%` magics, `!`/`!!` shell
commands, assignment forms, `?` help forms, and leading `/`, `,`, `;` call forms.
These produce UNSUPPORTED_SYNTAX and leave the entire cell unparsed. No lines
are stripped or translated. Markers inside valid Python strings/comments are
not commands. Ambiguous or unrecognized forms remain explicit SYNTAX_ERRORs;
this is not a complete IPython grammar. See the
[IPython syntax reference](https://ipython.readthedocs.io/en/stable/interactive/reference.html).

## Safety and limits

- Target code is never imported, evaluated, executed, or sent to a kernel/shell.
- JSON decoding necessarily reads and materializes the complete container,
  including stored output JSON. Output fields are never traversed for analysis,
  rendered, decoded as images, or retained in ParsedNotebook. Attachments and
  execution results cannot contribute syntax or evidence.
- No new dependency, cross-cell tracking, type inference, rule engine, statistical
  rules, directory scanning, or `statguard check` command is included.
- Standard Python support follows the running interpreter. IPython extensions
  such as top-level await are not specially transformed or executed.
- There is no streaming JSON reader, file-size limit, or memory sandbox. Very
  large input, including outputs, can consume resources during JSON decoding.
- The wrapper records are frozen; consumers must treat their retained ASTs as
  read-only, as with PythonSourceParser.

Tests cover mixed cells, both source encodings, empty inputs, positions, Unicode,
language validation, structural and syntax failures, recovery to later cells,
file errors, and execution/outputs safety. Permission errors are simulated at
the read boundary without modifying system permissions.
