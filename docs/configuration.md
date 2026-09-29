# Project configuration

StatGuard accepts a deliberately small project policy table in TOML:

```toml
[tool.statguard]
exclude = ["generated", "vendor"]
disable-rules = ["ML006", "ST002"]
fail-on = "warning"
```

The only supported keys are:

| Key | Type | Meaning |
| --- | --- | --- |
| `exclude` | array of nonempty strings | Additional exclusions passed to the Scanner, relative to the scan root. |
| `disable-rules` | array of nonempty rule IDs | Disable registered rules for this invocation. IDs are checked against the selected registry. |
| `fail-on` | `"warning"` or `"error"` | Finding threshold used when the CLI does not explicitly set `--fail-on`. |

Path, report format, report output, Python version, severity overrides, and
per-rule parameters are invocation or rule concerns and are not configurable
here. Unknown keys and invalid types fail with exit code 2 rather than being
silently ignored. TOML is read as data with Python's standard-library
`tomllib`; configuration is never imported or executed.

## Discovery and precedence

Without configuration options, one file is considered:
`pyproject.toml` in the current working directory. Missing files and files
without `[tool.statguard]` mean default policy. Discovery does not search
parent directories, the scan target, or nested projects. The current working
directory controls discovery; the scan path does not. For example, while in a
repository root, `statguard check nested/project` still uses the root
`pyproject.toml`. Select a nested policy explicitly when needed.

`--config PATH` reads that TOML file instead of automatic discovery. Relative
paths are relative to the current working directory. The explicit file may
have any name, but it must contain `[tool.statguard]` to provide policy.
`--no-config` disables automatic discovery. These options are mutually
exclusive; an explicitly requested but missing or invalid file is an error.

CLI policy is combined as follows:

- `--exclude` values follow configured `exclude` values.
- `--disable-rule` values follow configured `disable-rules` values and are
  checked against the selected RuleRegistry, including a custom registry
  supplied through the Python CLI API.
- Both lists are stably deduplicated. Exclusion path validation and semantics
  remain owned by the existing Scanner and are relative to the scan root,
  not the configuration file.
- Explicit `--fail-on warning|error` overrides configured `fail-on`.
- `--format` and `--output` remain CLI-only.

Configuration errors are written to stderr and return exit code 2 before any
scan or report output. They do not alter the JSON schema, report contents, or
default success behavior. No active-configuration banner is printed.

## GitHub Action

The composite Action exposes `config` and `no-config`. `config` is an optional
path relative to `GITHUB_WORKSPACE`; both the lexical path and its resolved
target, including symlinks, must remain inside the workspace. A nonempty
`config` cannot be combined with `no-config: true`. The boolean input accepts
exactly `true` or `false`. If no explicit config is provided, discovery uses
the Action's workspace-root `pyproject.toml`. Action arguments are still
passed to the CLI as a list with `shell=False`.

Project configuration is policy for a single CLI invocation. It does not
change Scanner or Analyzer APIs, add a runtime dependency, or make findings
more or less certain; disabled rules and failure thresholds only select which
existing diagnostics are active and how the command exits.
