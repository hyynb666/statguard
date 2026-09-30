# SARIF 2.1.0 and GitHub Code Scanning

StatGuard can emit SARIF 2.1.0 for integrations that accept static-analysis
results:

```text
statguard check . --format sarif
statguard check . --format sarif --output statguard.sarif
```

The reporter uses only the Python standard library. It maps one Finding to one
SARIF result, maps `error`/`warning`/`info` to SARIF `error`/`warning`/`note`,
and carries confidence, evidence category, explanation, and suggestion in
result properties. Registry metadata is attached only to the matching rule ID;
custom IDs without supplied metadata get a neutral descriptor. Scan errors and
notices are invocation notifications, not rule results. Findings alone do not
mark SARIF execution unsuccessful.

Python findings use repository-relative forward-slash paths and retain their
one-based line and column when the scanned file is under the selected base
directory. Outside paths become `file:` URIs and may not map to a repository
file in Code Scanning. Scan files inside the checked-out repository for useful
GitHub annotations.

Notebook findings identify the `.ipynb` artifact but have no SARIF physical
region. StatGuard line and column values refer to a code cell, not the raw
Notebook JSON file. The cell ordinal, original cell index, and in-cell location
are kept in `statguardCell`, `statguardCellIndex`, `statguardCellLine`, and
`statguardCellColumn` properties. GitHub can associate the alert with the
Notebook artifact, but this does not claim that its UI can navigate to a
physical JSON line. Cells are analyzed independently; stored outputs are never
analyzed.

The output is deterministic for the same findings, working directory, and
StatGuard version. Its `statguardFingerprint/v1` value is a stable SHA-256
identity for StatGuard SARIF results; it is not the CodeQL fingerprint
algorithm. For an outside-workspace `file:` URI, the fingerprint uses an
outside-workspace marker and basename to avoid embedding a machine-specific
absolute path; separate outside files with the same basename can therefore
share this fingerprint when their other finding fields match. Reports contain
no timestamps, AST objects, source snippets, Notebook outputs, or
external-service results. See [the report contract](reporting.md).

## Upload results from a workflow

StatGuard only creates a SARIF file. The calling workflow decides whether to
upload it. GitHub's [uploading SARIF documentation](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/integrate-with-existing-tools/upload-sarif-file)
uses `github/codeql-action/upload-sarif`; its current official action is
`github/codeql-action/upload-sarif@v4` and accepts the `sarif_file` input
([action definition](https://github.com/github/codeql-action/blob/main/upload-sarif/action.yml)).

Grant the workflow the narrow permissions needed for checkout and upload:

```yaml
permissions:
  contents: read
  security-events: write

jobs:
  statguard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: hyynb666/statguard@v1.0.0
        with:
          path: .
          format: sarif
          output: statguard.sarif
      - uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: statguard.sarif
```

The example does not set `fail-on`, so findings do not prevent upload. To use
Code Scanning for display without gating the workflow, leave the threshold
unset. The upload action requires Code Scanning availability and sufficient
repository permissions; fork pull requests, repository type, organization
policy, and GitHub plan can affect whether an upload is allowed.

### Upload and gate on findings

If warnings should also fail the job, let the upload run before enforcing the
StatGuard result. `continue-on-error` retains the step outcome while allowing
the upload to execute; the final step restores a failing job status:

```yaml
      - name: Scan with StatGuard
        id: statguard
        continue-on-error: true
        uses: hyynb666/statguard@v1.0.0
        with:
          path: .
          format: sarif
          output: statguard.sarif
          fail-on: warning
      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: statguard.sarif
      - name: Enforce StatGuard result
        if: always()
        env:
          STATGUARD_OUTCOME: ${{ steps.statguard.outcome }}
        shell: bash
        run: test "$STATGUARD_OUTCOME" = success
```

The scan step writes the report before returning its threshold exit code. A
report-generation or scan error returns 2 and is also retained in the SARIF
invocation notifications; the final enforcement step still fails the job.
If the report file is unavailable, the upload step can fail independently.
The StatGuard Action never uploads automatically and does not request
`security-events: write` itself.

## Scope and compatibility

`--format sarif` does not alter Console, HTML, or JSON behavior. JSON remains
schema 1.0. Project configuration intentionally does not accept a `format`
key; choose SARIF at the CLI or Action invocation. No SciPy, sklearn, schema
download, or GitHub client dependency is required to generate the report.
