# Compatibility policy for the planned v1.0 line

This document defines the compatibility boundary proposed for StatGuard v1.0.
The current development package is still `0.3.0.dev0`; v1.0.0 has not been
released. The policy takes effect for the public v1 line only when that release
is separately approved and published. The stable release remains v0.2.0.

## Supported runtime and package

- Python 3.11 or newer is supported. The project CI currently exercises Python
  3.11–3.14 on Windows and Linux.
- StatGuard has no runtime third-party dependencies. Build, test, and lint tools
  are development-only extras.
- `statguard --version`, `statguard --help`, and `python -m statguard` are
  supported entry points.

## CLI and exit status

The command form `statguard check <path>` accepts a Python file, Notebook, or
directory. The supported options are `--format`, `--output`, repeatable
`--exclude`, `--fail-on`, repeatable `--disable-rule`, `--config`, and
`--no-config`. The two configuration-selection options are mutually exclusive.

Exit status is part of the user-facing contract:

| Status | Meaning |
| ---: | --- |
| `0` | Scan completed without meeting an explicitly configured `--fail-on` threshold. Findings do not fail by default. |
| `1` | A Finding met the configured warning or error threshold. |
| `2` | Invalid invocation, configuration, input, parse, rule, or report error. |

Additive CLI options may be introduced compatibly. Existing option meaning,
output selection, and exit semantics should not change within v1. A change that
alters these contracts requires a compatibility review and release note.

## Built-in rule identifiers

The planned v1 default registry contains exactly these 11 built-in rules:
**ML001–ML009, ST001, and ST002**. Each ID is a stable diagnostic identifier
and is accepted by `--disable-rule` and the `disable-rules` project setting.
An additive rule may expand the default Finding set and must be documented and
called out in release notes. Renumbering or changing the meaning of an existing
ID is incompatible and requires an explicit migration decision.

The stable v0.2.0 release remains ML001–ML006, ML009, ST001, and ST002. It does
not contain ML007 or ML008. The current development package is not the stable
v0.2.0 release.

## JSON, SARIF, and other reports

- JSON schema version `1.0` is the machine-readable CLI contract. Its document
  contains `tool`, `version`, `schema_version`, `summary`, `files`, `findings`,
  `analysis_errors`, and `notices`. Finding and error fields are documented in
  [the reporting guide](reporting.md).
- SARIF output uses SARIF `2.1.0`. It is a separate format and does not change
  the JSON schema. Notebook cell coordinates are properties; raw Notebook JSON
  line numbers are not invented.
- Console, JSON, HTML, and SARIF describe the same Finding model. Output order
  is deterministic. HTML remains offline, escapes untrusted text, and uses the
  documented Content Security Policy.
- New optional JSON fields require a schema compatibility review. Removing or
  reinterpreting existing fields requires a new documented schema contract.

## Project configuration

Only `[tool.statguard]` keys `exclude`, `disable-rules`, and `fail-on` are
supported. Config is read as TOML data and is never executed. By default only
the current working directory's `pyproject.toml` is discovered; `--config`
selects a file and `--no-config` disables discovery. Adding keys is compatible
when validation remains strict for unknown keys; changing precedence or the
meaning of existing keys requires a compatibility review.

## Inline Finding suppression

The supported comment forms are `# statguard: ignore RULE_ID` on the Finding's
physical line and `# statguard: ignore-next-line RULE_ID` on the immediately
following physical line. Multiple explicit IDs may be comma-separated.
Directives are recognized from Python comment tokens; they are line-local,
rule-specific, and Notebook-cell-local. Wildcard, file-wide, block, malformed,
and unknown-ID directives do not suppress findings. Suppressions do not hide
analysis errors or notices. Changing this grammar requires a compatibility
review, documentation, and regression tests.

## GitHub Action

The composite Action contract has nine inputs: `path`, `python-version`,
`format`, `output`, `fail-on`, `disable-rules`, `exclude`, `config`, and
`no-config`. Inputs and workspace containment behavior are described in the
[Action guide](github-action.md). Additional optional inputs may be added
without changing the meaning of these inputs. Changing a default, accepted
value, path boundary, or input meaning requires a compatibility review.

The Action writes reports; it does not upload SARIF or other artifacts. Its
current stable README and Action guide reference remains `@v0.2.0` until a
separate release task updates them.

## Public Python API

The deliberately supported core API is `statguard.__version__` and the
following names imported from `statguard.core`:

```python
from statguard.core import Confidence, Evidence, Finding, Rule, RuleRegistry, Severity
```

Their fields, constructor compatibility, rule metadata, and registry behavior
are documented in [Core interfaces](core-interfaces.md). New APIs can be added
compatibly. Removing or changing these named exports or their documented
behavior requires a compatibility review and release note.

The individual Parser classes, `ParsedSource`, `AnalysisContext`, `Analyzer`,
`Scanner`, provenance helpers, Reporter functions, and modules below
`statguard.*` are documented for integrations but remain evolving interfaces;
they are not covered by the same compatibility guarantee unless explicitly
listed above. Underscore-prefixed helpers are internal implementation details.

## Versioning policy

Within the v1 line, patch releases are intended for compatible fixes, including
reducing false positives, improving diagnostics without changing their public
shape, and correcting documentation. Minor releases may add rules or supported
analysis patterns; because enabled rules can add Findings, these changes must
be documented in release notes. Major releases are required for incompatible
changes to the CLI, exit status, JSON contract, rule IDs, Action inputs, or
listed Python core API.

This boundary means the documented contracts have an explicit compatibility
policy. It does not mean StatGuard understands every statistical workflow or
that the analyzer's internal implementation is frozen.
