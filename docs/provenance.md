# Data provenance contract (Issue #8)

`AnalysisContext.provenance` lazily caches a `ProvenanceTracker` using the same
`ParsedSource` and `SymbolResolver` as `context.symbols`. No target module is
imported and no expression or Notebook output is executed. This API emits no
Findings and makes no data-leakage judgment.

## Queries and records

- `resolve(original_expression)` returns its `DataOrigin` at the actual use site.
- `for_binding(binding)` queries a specific immutable binding version, never the
  last binding with the same name.
- `splits` lists supported split operations in deterministic source order.
  This is document order, not proof that functions execute in that order.
- Records are frozen. `DataOrigin` contains an ID, kind, original AST evidence,
  source location, original one-based Notebook `cell_index`, `known`, reason,
  `sources`, `inputs`, `roles`, and optional resolved `callee`.
- `CallInput` pairs a positional index or keyword name with an input record.
  A None keyword name represents `**kwargs`; unsupported expansion is unknown.
- `SplitRole` identifies the split operation, zero-based input array index,
  and `train` or `test` role. It does not use variable spelling.

IDs encode path, cell index, original AST node index and (for bindings) binding
order. They are deterministic for the same input, independent of query order,
and are not persistent identifiers across source edits. AST indexes supply only
identity; binding and call facts come from SymbolResolver, not AST walk order.
Records share the parser-owned AST. As with ParsedSource, callers must treat raw
AST nodes as read-only; frozen wrappers do not freeze AST internals.

`known` describes a supported *local relationship*, conditional on successful
execution of the declared API; it does not prove input contents, runtime types,
call success or statistical safety. An identified split can have unknown input
origins. Unknown records include reasons. Aliases preserve their source's status.

## Crucial distinction: arguments versus data lineage

`inputs` records which expressions were passed to a call. An arbitrary function
may discard them and return unrelated data, so a generic call is `kind="call"`,
`known=False`, has no proven `sources`, and does not inherit train/test roles.
Its argument records and callee/receiver/constructor evidence remain inspectable.
A function merely named transform, fit_transform or train_test_split proves no
library identity or return semantics.

`sources` records supported direct relations: binding/alias edges, recognized
split-output edges and recognized transformation edges. Follow these edges to
trace data; do not treat generic `inputs` as proof of lineage. Reassignments create
new versions. A previous transformation retains the input binding it read even
if the input variable is later rebound. Barriers in SymbolResolver invalidate
uncertain bindings; provenance never restores those old versions by name.

## Supported sklearn semantics

Library-specific knowledge lives only in `provenance_sklearn.py`, not in the
generic binding tracker or provenance graph. No sklearn runtime dependency is
added. The explicit public API contracts are:

- [train_test_split](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.train_test_split.html):
  only a resolved `sklearn.model_selection.train_test_split` is recognized.
  Imports, module aliases and callable aliases are supported. Explicit positional
  arrays map to alternating train/test outputs (two per array), including X/y.
  Flat tuple/list targets must have exactly that size. Aliasing the split result
  before flat unpacking is supported. Each output retains the split ID, input
  array index and source; unrelated split calls have different IDs. Options are
  recorded but their runtime validity is not evaluated.
- [StandardScaler](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html):
  `transform` and `fit_transform` on a receiver with an explicit public
  `sklearn.preprocessing.StandardScaler()`, `MinMaxScaler()` or `RobustScaler()` construction preserve the direct X
  source and its roles. X may be positional or an unambiguous keyword. Other
  arguments are recorded, but y, sample weights and fitted state are not merged
  into X's provenance. Direct constructor chains and receiver aliases work.

This small allowlist is deliberate. Other transformers, subclasses, factories,
private import paths, pipelines and `fit(...).transform(...)` are not inferred.
Supporting another API requires a documented contract and positive/negative
fixtures. A supported method does not prove the estimator was fitted correctly.
Monkey-patching inside opaque imported functions and nonstandard import hooks
are outside the declared-import model, as in SymbolResolver.

## Boundaries and compatibility

Starred/nested unpacking, mismatched output counts, `*arrays`, `**options`,
unsupported call signatures and dynamic targets never acquire split roles.
Complex branches, loops, dynamic execution, attribute/subscript mutation and
unknown side effects retain SymbolResolver's conservative invalidation policy.
This can lose real relationships; it must not invent them. In particular, an
unresolved loader call can invalidate earlier imported names. Re-importing an
explicit API can establish a new binding.

Functions remain independently analyzed: local imports work, module imports
referenced inside functions remain unknown because invocation-time globals are
not proven. There is no cross-function, cross-file, cross-cell or historical
Notebook execution analysis. Undefined input X is an unknown source occurrence,
not a fabricated dataset inferred from its name.

SymbolValue gained optional `unpack_source`, `unpack_index`, `unpack_size`
syntax evidence. Its existing unknown classification for unpacking is unchanged;
only the provenance adapter interprets recognized split projections. The resolver
also exposes its parser-owned `parsed` unit to reject mismatched tracker inputs.
Parser, Analyzer, Finding, Rule, CLI and Reporter behavior is unchanged. The provenance layer itself emits no diagnostics. Issue #9 adds [ML001](ml001.md)
as a separate consumer without changing the JSON report schema.

## Review robustness

Provenance dependencies are materialized with an explicit postorder stack and
cached per symbol/binding. Long alias and transformation chains do not depend on
Python's recursion limit or on querying earlier bindings first. Regression tests
cover 1,200 binding versions in both forward and reverse query order, as well as
AST relationships for transformations before and after splitting. These records
remain evidence only; they do not issue leakage diagnoses.
