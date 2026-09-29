# GitHub Action

StatGuard provides a composite GitHub Action for running its static scan in a
workflow. The Action is part of development toward v0.2.0. **The stable v0.1.0
release and tag do not include `action.yml`.** Until v0.2.0 is released,
`hyynb666/statguard@main` is a moving development reference and can change.
After a stable v0.2.0 release, the recommended reference will be
`hyynb666/statguard@v0.2.0`.

## Basic use

```yaml
jobs:
  statguard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: hyynb666/statguard@main
        with:
          path: .
```

`path` is relative to `GITHUB_WORKSPACE`, the checked-out caller repository.
The Action's own source is installed from `GITHUB_ACTION_PATH`; it is never the
default scan target. The Action does not check out or execute analyzed Python
files or Notebook cells.

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `path` | `.` | Python file, Notebook, or directory to scan, relative to `GITHUB_WORKSPACE`. |
| `python-version` | `3.12` | Python version configured by `actions/setup-python@v6`. The project CI currently covers Python 3.11–3.14. |
| `format` | `console` | `console`, `json`, `html`, or `sarif`, passed to `statguard check --format`. |
| `output` | empty | Optional report path, passed to `--output`; omitted when empty. Relative paths resolve from `GITHUB_WORKSPACE`. |
| `fail-on` | empty | Empty, `warning`, or `error`. Empty preserves the CLI default where Findings do not fail the step. |
| `disable-rules` | empty | Comma-separated rule IDs, for example `ML006, ST002`. The Action does not maintain its own rule registry. |
| `exclude` | empty | Newline-separated relative exclusions, passed as repeated `--exclude` arguments. Blank lines are ignored. |
| `config` | empty | Optional TOML configuration path, relative to `GITHUB_WORKSPACE`; passed to `--config`. Resolved paths must remain inside the workspace. |
| `no-config` | `false` | Exact `true` or `false`. `true` passes `--no-config`; it cannot be combined with a nonempty `config`. |

Exclusions use the same path semantics as the CLI: they are relative to the
selected scan root. Spaces inside paths are preserved.

If `config` is empty, StatGuard's normal current-working-directory discovery
applies. Since the Action runs in `GITHUB_WORKSPACE`, this means its root
`pyproject.toml`. Set `no-config: true` to bypass it. See the
[configuration guide](configuration.md) for supported keys and precedence.

## Failure thresholds

To fail the job when at least one warning or error Finding is present:

```yaml
- uses: hyynb666/statguard@main
  with:
    path: .
    fail-on: warning
```

Without `fail-on`, Findings alone leave the step successful. With
`fail-on: warning`, warning and error Findings produce exit code 1; with
`fail-on: error`, only error Findings do. Invalid inputs, scan errors, parse
errors, rule errors, and report errors preserve the CLI's exit code 2.

## Reports

JSON, HTML, and SARIF can be saved for a later workflow step. See the
[SARIF and Code Scanning guide](sarif.md) for upload patterns. Example JSON:

```yaml
- uses: hyynb666/statguard@main
  with:
    path: .
    format: json
    output: statguard-report.json
```

HTML reports can be uploaded by the calling workflow when desired:

```yaml
- uses: hyynb666/statguard@main
  with:
    path: .
    format: html
    output: statguard-report.html
- uses: actions/upload-artifact@v4
  with:
    name: statguard-report
    path: statguard-report.html
```

The StatGuard Action itself does not upload artifacts. Artifact retention and
access are controlled by the caller's workflow.

For SARIF, the Action only writes the report. It never uploads results or
requests `security-events: write` permission itself.

## Security model and limitations

- The Action installs StatGuard from the same `GITHUB_ACTION_PATH` revision
  selected by `uses`; it does not install a potentially unrelated PyPI version
  or clone the repository again.
- Inputs are translated by a small Python standard-library runner into an
  argument list and launched without a shell. Input text is never interpolated
  into a shell command. Scan targets and explicit configuration paths are
  restricted to `GITHUB_WORKSPACE`, including resolved symlinks. Output paths
  are also constrained to that workspace, including resolved parent symlinks.
- StatGuard parses source statically. It does not import or execute analyzed
  Python or Notebook code and does not analyze Notebook outputs.
- GitHub Actions permissions, runner selection, dependency policy, and artifact
  upload policy remain the calling workflow's responsibility.
- Static findings are limited to documented, resolvable code patterns. No
  finding does not prove that a workflow is statistically sound.
- The `@main` reference is mutable during v0.2 development. Pin a reviewed
  commit if a moving development reference is unsuitable for your workflow.
