# Import resolution and basic bindings

Issue #7 adds syntax provenance for a single ParsedSource. It does not infer
statistical harm, train/test provenance, runtime types, or the effects of arbitrary
library implementations. No source imports, expressions, functions, or cells
are executed.

## API

```python
from statguard.context import AnalysisContext
from statguard.parsers import PythonSourceParser

unit = PythonSourceParser().parse_source(
    "from package import Factory as F\nobj = F()\ncopy = obj\n"
)
context = AnalysisContext(unit)
symbols = context.symbols
call = context.calls[0].node
assert symbols.resolve(call.func).qualified_name == "package.Factory"
assert symbols.resolve(call).kind == "call"
assert symbols.resolve(call).qualified_name is None
```

`AnalysisContext.symbols` lazily builds and caches a
`statguard.symbols.SymbolResolver` over the original AST. Construction does not
change Parser, Analyzer, Finding, Rule or RuleRegistry contracts. Replacing a
context's parsed source with dataclasses.replace creates a fresh cache. Notebook
contexts have independent resolvers; no cell imports or assignments are shared.

- `resolve(expression)` queries an original AST expression at its point of use.
  It never resolves using the final state of the module.
- `binding_for(name_reference)` returns the exact Binding version read by an
  original ast.Name, or None for unbound/unsupported references.
- `bindings` is an immutable tuple of Binding records. Each has a name, scope
  AST node, defining/invalidation AST node, source location, order, and value.
  Order records analysis events; only compare order within the same scope.
  Rebinding creates another record and does not rewrite an earlier reference.
- `SymbolValue` is a frozen syntax record. Its kind is import, alias, call,
  attribute, literal, or unknown. It retains the original AST node. Aliases point
  to a Binding; attributes retain base and attribute; calls retain callee.
  Argument ASTs are on the original call node, and supported argument
  expressions can be queried separately at their own point of use.
- `origin` follows assignment aliases. `qualified_name` only follows import
  paths and their attribute chains. Call results and instance methods have no
  inferred qualified name.
- `is_unknown` reports unresolved provenance, following aliases, receiver bases
  and callees. False means the source expression's provenance was recorded,
  **not** that a runtime value, type, successful execution, or data lineage is
  known. Unknown origins retain a reason.

## Supported relationships

Absolute import, from-import and aliases retain their declared import path.
For `import a.b`, the local name is `a`; for `import a.b as p`, `p` refers
to the declared path `a.b`. Chained attributes on imported names are resolved
syntactically. No library is loaded, no re-export is verified, and a coincident
unimported name does not establish any library identity.

Straight-line Assign and AnnAssign record RHS provenance. Name-to-name aliases
retain the binding version at assignment time, including unknown source inputs.
Chained simple assignment shares the RHS record. Reassignment, deletion and
augmented assignment replace or invalidate the current binding. Annotation-only
statements do not replace an existing value. Literals are retained as AST
constants, without evaluating expressions.

For `obj = F()`, the creation call's callee can resolve to an imported path;
this does not prove that F is a class rather than a factory. For
`y = obj.method(X)`, the call retains its receiver's creation provenance,
method spelling and argument AST. `F().fit(X).transform(Y)` retains nested
calls but does not assume fit returns self, infer transform's runtime identity,
or propagate the lineage of X/Y.

## Scopes, order and conservative limits

The module and each supported function body use independent environments.
Parameters are unknown values. Function-local imports and assignments can be
tracked in statement order. Function bodies do not inherit globals or closure
bindings: even a module-level import referenced inside a function is unknown
in this version. This avoids assuming function invocation time or late-bound
global state. Functions with global/nonlocal declarations are unsupported.
Class bodies and functions inside unsupported control flow are not resolved.
Statements after an explicit return/raise are left unresolved.

Conditionals, loops, try/except, with, match, class statements, and unsupported
expressions are not executed or merged. A barrier invalidates current bindings,
including aliases, and marks possibly written names unknown. Calls with an
unresolved callee, wildcard imports, dynamic import/eval/exec/reflection,
attribute/subscript writes, and function headers with defaults/decorators or
annotations are conservative barriers too. Unsupported expression examples
include comprehensions, lambdas, named expressions, operators, await and yield.
This deliberately loses some unchanged bindings; a subsequent explicit import
or supported assignment can establish a new binding. Unpacking is unknown and
does not identify split outputs.

Calls on imported symbols retain declared provenance but opaque library side
effects, arbitrary monkey-patching inside imported functions, cross-file
behavior, and actual method dispatch are not modeled. These facts cannot prove
object type, library implementation, call success, input/output lineage or
statistical safety. Rules must abstain when their required evidence is missing.
Notebook analysis follows document order only; it does not recover execution
history. Unknown resolver facts are not statistical Findings or parser errors.

The implementation uses only the standard library, parser-owned nodes and
ParsedSource.location_for. Tests cover import paths, versioned aliases,
reassignment, local scopes, unsupported effects, original AST identity, and
Notebook isolation through an Analyzer test rule.

### Review note: imports used inside functions

A module import is not a guaranteed binding at function invocation time. For
example, `from package import Factory; def f(): ...` may be followed by a
reassignment or deletion of Factory, and callers may modify the module namespace.
Neither a definition-time snapshot nor the final module environment proves the
binding when f runs. This version therefore keeps such references unknown,
including an otherwise simple StandardScaler preprocessing function. A local
import inside the function can establish a supported binding. Parameters and
later local assignments/annotations must never fall back to a module import.

Supporting module import *candidates* separately from proven bindings could be a
future API extension, but must not expose a candidate as a resolved qualified_name.
No call-site or cross-function state analysis is introduced in this version.
