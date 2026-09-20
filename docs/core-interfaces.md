# Core interfaces

`statguard.core` exports `Finding`, `Evidence`, `Severity`, `Confidence`,
`Rule[ContextT]`, and `RuleRegistry[ContextT]`. These interfaces represent
observations, rule contracts, and explicit rule selection. The separate
[Analysis Context and Analyzer](analyzer.md) now connect them to existing parsers.
Built-in detection rules and reports remain unimplemented.
All implementation dependencies are in the Python standard library.

## Finding

```python
from statguard.core import Confidence, Evidence, Finding, Severity

finding = Finding(
    rule_id="TEST001",
    file_path="analysis.py",
    line=4,
    column=5,
    severity=Severity.INFO,
    confidence=Confidence.LOW,
    message="A fixture observation was supplied.",
    explanation="This example does not establish statistical harm.",
    suggestion="Inspect the fixture.",
    evidence=Evidence.GENERAL_ANALYSIS_ADVICE,
)
```

Finding is a frozen, slotted dataclass with value equality and hashing. It accepts
the following fields through its constructor and exposes them as attributes:

| Field | Contract / default |
| --- | --- |
| `rule_id` | Required nonempty string; stable rule identifier. |
| `file_path` | Required nonempty string; file path or diagnostic label. |
| `line` | Required positive integer, one-based; booleans/floats are rejected. |
| `column` | Optional positive integer, one-based Unicode character column; None when unavailable. |
| `cell_index` | Optional positive integer; original Notebook position counting all cell types. |
| `message` | Required nonempty string describing the observation. |
| `explanation` | Required nonempty string explaining the cause/risk and uncertainty. |
| `suggestion` | Required nonempty string containing a practical next step. |
| `severity` | Severity.ERROR / WARNING / INFO; default WARNING. |
| `confidence` | Confidence.HIGH / MEDIUM / LOW; default LOW. |
| `evidence` | An Evidence member; default UNDETERMINED. |
| `cell` | Legacy optional positive code-cell ordinal, counting code cells only. |

Severity and confidence also accept their exact lowercase string values and
normalize them to enum members. Wrong types raise TypeError; unknown values,
blank required strings, and nonpositive coordinates raise ValueError. Paths and
IDs are not normalized and no files are accessed. IDs are not restricted to
currently planned statistical/ML rule IDs.

Severity describes the diagnostic level; confidence describes the rule author's
confidence in the observation, not a measured probability. Neither determines
the PRD Evidence category. The conservative LOW/UNDETERMINED defaults do not
assert a violation. The Analyzer retains this category without promoting it to a confirmed
violation, even when severity is ERROR or confidence is HIGH.
Rules should provide an explicit evidence category when their required evidence
has been established. No category permits inventing source evidence or claiming
measured statistical effects from syntax alone.

### Locations and Notebook mapping

For Python source, `line` refers to the file; `cell_index` and `cell` are None.
For a Notebook, line/column are relative to the code cell, never the JSON file.
Public columns count Unicode characters (tabs count as one), as in SourceLocation.
The model permits diagnostic labels and does not guess input type from extensions.

Pass `NotebookCell.cell_index` as `Finding.cell_index` and
`NotebookCell.code_cell_index` as `Finding.cell`. For markdown, code, raw, code,
the second code cell has `cell_index=4` and `cell=2`. These are independent
identifiers, not aliases. Both are one-based. If both are present, `cell` cannot
exceed `cell_index`. If only one is supplied, the other stays None: the original
position cannot be derived from the code-cell ordinal or vice versa.

This preserves the PRD's one-based code-cell reporting convention while adding
the requested original Notebook position. Later integration should populate both
from NotebookParser. Document order still does not prove historical execution
order. PythonSourceParser, ParsedSource, NotebookParser and their ASTs are unchanged.

### Compatibility

The original positional constructor order is preserved:
`Finding(rule_id, path, line, column, message, risk, recommendation, evidence, cell=None)`.
Existing keyword calls also work. New fields are keyword-only; column may now
be omitted or None. The new string names are constructor aliases and read-only
properties over the existing stored fields:

| New name | Existing stored field |
| --- | --- |
| `file_path` | `path` |
| `explanation` | `risk` |
| `suggestion` | `recommendation` |

Equal old/new arguments are accepted; conflicting values raise ValueError.
There is no duplicate mutable state. `dataclasses.replace` should use stored
names (`path`, `risk`, `recommendation`) when changing these values. Existing
replace calls and positional callers are covered by regression tests.
`dataclasses.asdict` still uses stored names, with the additional severity,
confidence and cell_index fields. It is not a versioned JSON reporting schema.

Validation is deliberately stricter than the initial foundation: invalid enum
values, non-integer coordinates (including bool), and empty diagnostic text are
rejected. Existing valid findings retain their behavior; consumers passing
invalid values need to correct them.

## Rule

Rule remains a generic Protocol. New implementations provide `rule_id`, `name`,
`description`, `default_severity`, and synchronous
`check(context) -> Iterable[Finding]`. An iterable may be a list, tuple, or
generator. Abstention is an empty iterable; parse errors and coverage notices
must not be converted into invented statistical violations.

Explicit subclasses can inherit `name=rule_id` and
`default_severity=Severity.WARNING`. Their inherited `analyze(context)` forwards
to `check(context)` for existing callers. Override `check`; inheriting both entry
points without an implementation is rejected at registration. Structural rule
objects need not inherit Rule, but must provide the new metadata and check entry.

Rules never print diagnostics or execute scanned source. A rule should pass its
default severity explicitly when constructing a Finding if it wants that default
to apply. The registry does not rewrite results or apply metadata to findings.
Rules receive AnalysisContext from the Analyzer. Conservative data-flow facts
and library-specific reasoning are still outside this core contract.

```python
from statguard.core import Rule, RuleRegistry, Severity


class EmptyFixtureRule(Rule[None]):
    rule_id = "TEST001"
    name = "Empty fixture"
    description = "Test-only rule that emits no findings."
    default_severity = Severity.INFO

    def check(self, context: None):
        return ()


registry = RuleRegistry[None]()
registry.register(EmptyFixtureRule())
assert list(next(registry.iter_enabled()).check(None)) == []
registry.disable("TEST001")
assert list(registry.iter_enabled()) == []
```

## RuleRegistry

- `register(rule, *, enabled=True)` registers one instance. It checks nonempty
  metadata, a valid default severity, and a synchronous callable accepting one
  context argument. It does not invoke detection. Registration errors leave the
  registry unchanged. Classes, missing/noncallable entry points, unsupported
  async methods, and invalid metadata raise TypeError or ValueError with details.
- Duplicate IDs raise ValueError even if the existing rule is disabled. IDs are
  case-sensitive and compared exactly; use stable IDs without surrounding whitespace.
- `get(rule_id)` returns the originally registered object, enabled or disabled.
  `iter(registry)` lists all original objects sorted lexicographically by rule ID;
  `len(registry)` counts all registrations. This preserves the initial API.
- `enable(rule_id)` / `disable(rule_id)` are idempotent for known IDs.
  `is_enabled(rule_id)` returns their selection state. All ID lookups and toggles
  raise KeyError for an unknown rule.
- `iter_enabled()` returns a snapshot of enabled rules, sorted by ID, with a
  uniform `check(context)` entry point. Disabled rules are excluded from that
  selection, but remain directly accessible. No rule is executed by selection.

### Legacy rules and limits

Existing analyze-only instances with `rule_id` and `description` still register.
Lookup and ordinary iteration preserve their object identity. For
`iter_enabled()`, a small internal adapter exposes `check(context)` by forwarding
to their `analyze(context)`, with default name equal to the ID and WARNING
severity unless the old object already supplies valid metadata. The adapter
does not modify the original object or execute it during registration. Existing
explicit Rule subclasses that only override analyze are handled in the same way.
New typed implementations should implement the expanded Rule contract.

Metadata must remain stable after registration. Disabling affects selection,
not permission to call an object directly. Registration validates the interface,
not the detection result: it cannot guarantee an implementation returns Findings
or stays silent without running it. Each rule's own tests must verify that
contract. Only trusted, explicitly supplied rule implementations are registered;
the registry has no automatic module imports, plugin discovery, configuration
files, or execution loop. Finding sorting/deduplication and report serialization
belong to later integration.
