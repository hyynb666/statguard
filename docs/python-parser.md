# Python source parser

`PythonSourceParser` extracts syntax for later analysis. It neither identifies
statistical errors nor resolves imports, aliases, types, values, or data lineage.
The public API is available from `statguard.parsers`. Existing `statguard.core`
interfaces and the help/version CLI are unchanged.

## Entry points and successful results

```python
from statguard.parsers import PythonSourceParser, SourceParseError

parser = PythonSourceParser()
unit = parser.parse_source("import pkg as p\nx = p.run(data)\n", path="example.py")
assert unit.calls[0].name == "p.run"
assert unit.calls[0].node is unit.assignments[0].node.value

try:
    from_file = parser.parse_file("analysis.py")
except SourceParseError as error:
    print(error)  # Includes path, error code and available line/column.
```

- `parse_source(source: str, *, path: str = "<string>") -> ParsedSource` parses
  text without file access. `path` is a diagnostic label, not a file to load.
- `parse_file(path: str | PathLike[str]) -> ParsedSource` reads a `.py` file
  (extension checked case-insensitively). It honors Python's UTF-8 default,
  UTF-8 BOM, and PEP 263 encoding cookies. Newlines are retained in `source`;
  a decoded BOM is omitted. Directories are not scanned recursively.
- `ParsedSource.path`, `.source`, and `.tree` retain the label, decoded source,
  and original `ast.Module`. Empty files return a successful empty module.

The following tuples index nodes in the same AST, without copying or rewriting
expressions. Each record has `.node`, `.location`, and `.enclosing_definitions`.

| Index | AST nodes and available syntax |
| --- | --- |
| `imports` | Import / ImportFrom; `node.names` contains aliases with `name` and `asname`; ImportFrom retains `module` and relative `level`. Star imports remain `*`, without invented bindings. |
| `assignments` | Assign / AnnAssign; original targets, values, and annotations. Destructuring is retained, not converted into data-flow facts. Annotation-only statements have `value=None`. |
| `calls` | CallInfo with raw Call, syntactic `name`, `is_unknown`, `args`, and `keywords`. Arguments are AST expressions, never evaluated Python values. |
| `functions` | FunctionDef / AsyncFunctionDef; names, parameters, annotations, decorators, defaults, return annotations, and bodies remain on `node`. |

Indexes use ascending source line/column, with AST preorder for ties. This is a
deterministic syntax listing, **not execution order**. Nested calls can start at
the same position. Imports/calls in a conditional or unused function are still
indexed and must not be assumed to execute.

`enclosing_definitions` holds function, async-function, and class AST ancestors,
outermost first. It is syntax ancestry only: decorators, annotations and defaults
also have the declaration as an ancestor even when their evaluation would occur
in another scope. Lambdas and comprehensions do not add entries to this tuple;
their actual syntax is retained in the full tree. This field is not a name-binding
or runtime-scope model.

## Call names and uncertainty

A Name, or an Attribute chain rooted in a Name, yields its syntactic dotted name.
For example, `sklearn.model_selection.train_test_split(...)` yields that full
name, without library-specific handling. `alias.run(...)` stays `alias.run`
regardless of nearby imports, assignments, shadowing, or monkey-patching.

Calls rooted in dynamic expressions have `name=None` and `is_unknown=True`:
`factory().fit(...)`, `handlers[key](...)`, `getattr(obj, name)(...)`, and lambdas
invoked directly. Inner calls are separately indexed. The complete dynamic
expression is always available through `call.node.func`.

`args` preserves positional arguments and `ast.Starred` nodes for `*args`.
`keywords` preserves `ast.keyword`; its `arg` is `None` for `**kwargs`. Reading a
literal's `ast.Constant.value` describes the literal itself, not proof of an
inferred variable value. There is no evaluation, constant folding, or call-result
prediction, including for apparently simple expressions.

## Locations

`SourceLocation` provides `path`, `line`, `column`, `end_line`, and `end_column`.
Public coordinates are one-based Unicode character positions, compatible with
Finding's one-based convention; the end position is exclusive. A tab counts as
one character, not a visual tab width. Combining characters count separately.
Raw AST nodes retain Python's zero-based UTF-8 byte columns. See the
[Python AST location reference](https://docs.python.org/3/library/ast.html#ast.AST).

`unit.location_for(node)` converts positions for any located node from that unit,
including import aliases, positional arguments and keyword values. Nodes such
as `ast.Module` or `ast.Load` have no location and raise `ValueError`. Use nodes
from the unit's original, unmodified tree. Frozen wrappers do not make the AST
immutable: consumers must treat it as read-only to keep indexes/locations valid.

Source line mapping respects LF, CRLF, and CR. Unicode separators inside string
literals are not incorrectly treated as Python newlines. Comments and original
spelling remain in `.source`; comments are not separate AST nodes.

## Failures

`SourceParseError` exposes `.code`, `.path`, `.message`, `.line`, and `.column`.
Unknown error positions are `None`, not fabricated line 1 locations. Original
exceptions are chained for debugging. No failed parse returns a successful unit
or creates a statistical Finding.

| ParseErrorCode | Meaning |
| --- | --- |
| READ_ERROR | Missing/invalid path, directory instead of file, permission denial, or other file-read failure. |
| ENCODING_ERROR | Invalid source bytes, unknown/conflicting encoding declaration, or unencodable source text. |
| SYNTAX_ERROR | Grammar failure, including indentation errors, notebook magics presented as Python, or null characters. |
| UNSUPPORTED_FILE | `parse_file` received a path without a `.py` extension. |
| RESOURCE_LIMIT | Python's AST parser raised RecursionError. |

The parser does not silently skip malformed source or attempt partial recovery.
A future scanner should catch errors per source unit and continue other inputs
where possible. Passing a non-string to `parse_source` is API misuse and raises
TypeError.

## Boundaries and next integration

- Supported grammar follows the Python interpreter running StatGuard. Newer
  language features may fail on older interpreters; no grammar backport is used.
- `ast.parse` checks syntax, not every compiler/runtime constraint (for example,
  it can represent a top-level return). Successful parsing is not proof of valid
  execution or statistically correct code.
- Assign/AnnAssign are indexed; AugAssign, NamedExpr, classes, comprehensions,
  and all other syntax remain in the tree but do not get additional public indexes.
- No target imports, `eval`, `exec`, shell execution, or target function calls
  occur. The source may import packages that are not installed.
- No resource sandbox, file-size limit, or protection against all interpreter
  memory/stack exhaustion is provided. Untrusted input is never executed, but
  hostile input can still consume parser resources.
- [NotebookParser](notebook-parser.md) reuses `parse_source` for each Python code
  cell, attaching cell identity and document-order notices separately. Directory
  scanning, scan CLI, reporters, rule engine, and statistical rules remain
  unimplemented.

Tests cover both entry points, aliases, relative imports, dynamic calls,
annotations, nesting, encoding/newline variants, locations, explicit errors,
and side effects that must never run. Permission errors are simulated at the
read boundary so results do not depend on Windows ACLs or runner privileges.
