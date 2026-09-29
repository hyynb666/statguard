# Security Policy

## Supported versions

Security fixes are considered for the latest release and the current `main`
branch. When additional release lines exist, this section will identify the
supported versions.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting if it is available for this
repository. If it is unavailable, contact the repository maintainer through an
appropriate private channel available from the maintainer's GitHub profile. If
neither route is available, open a public issue containing only a request for a
private reporting channel; do not include vulnerability or exploit details.
Do not publish exploitable details before maintainers have had a reasonable
opportunity to review and address the report. No dedicated security email is
currently provided.

Please include the affected version or commit, a concise description of the
impact, steps to reproduce, and any safe proof of concept. Avoid attaching
credentials, private datasets, or unrelated personal information.

## Security-sensitive behavior

StatGuard is designed to analyze untrusted Python and Notebook source
statically. It must not execute user code by default. Reports involving
accidental source or Notebook execution, unsafe path handling, HTML/report
injection, or parser handling of crafted inputs should be treated as
security-sensitive.

Do not submit real secrets or exploitable payloads in public issues. Use the
private reporting route above and provide only the minimum information needed
to reproduce the problem safely.
