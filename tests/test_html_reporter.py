"""Offline HTML report rendering and escaping guarantees."""

from html.parser import HTMLParser

from statguard.analyzer import AnalysisError, AnalysisErrorStage, AnalysisResult
from statguard.core import Confidence, Evidence, Finding, Severity
from statguard.parsers import NotebookIssue, NotebookIssueCode
from statguard.reporters import render_html
from statguard.scanner import ScanNotice, ScanReport


class StructureInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts = 0
        self.remote_urls: list[str] = []
        self.event_attributes: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.scripts += 1
        for name, value in attrs:
            if name.startswith("on"):
                self.event_attributes.append(name)
            if name in {"src", "href"} and value and value.startswith(("http:", "https:")):
                self.remote_urls.append(value)


def test_html_report_shows_full_finding_and_notebook_location() -> None:
    finding = Finding(
        "ML001",
        "experiment.ipynb",
        7,
        4,
        "Potential preprocessing leakage before train/test split.",
        "The transformed input may include held-out observations.",
        "Split before fitting the transformer.",
        Evidence.POTENTIAL_STATISTICAL_RISK,
        severity=Severity.WARNING,
        confidence=Confidence.HIGH,
        cell=2,
        cell_index=4,
    )
    report = ScanReport(
        (
            AnalysisResult(
                "experiment.ipynb", findings=(finding,), analyzed_units=2, completed_units=2
            ),
        ),
        enabled_rule_count=4,
    )

    html = render_html(report)

    assert "StatGuard Analysis Report" in html
    assert "ML001" in html and "warning" in html and "Confidence: high" in html
    assert "experiment.ipynb" in html and "cell 4" in html and "line 7, column 4" in html
    assert Evidence.POTENTIAL_STATISTICAL_RISK.value in html
    assert "The transformed input may include held-out observations." in html
    assert "Split before fitting the transformer." in html
    assert "Scanned files" in html and "Findings (1)" in html


def test_html_counts_only_rules_and_findings_present() -> None:
    findings = tuple(
        Finding(
            rule,
            f"{rule}.py",
            line,
            1,
            f"message {rule}",
            "risk",
            "fix",
            Evidence.POTENTIAL_STATISTICAL_RISK,
            severity=severity,
        )
        for rule, line, severity in (
            ("ML001", 1, Severity.WARNING),
            ("ML002", 2, Severity.WARNING),
            ("ML003", 3, Severity.INFO),
            ("ML004", 4, Severity.ERROR),
        )
    )
    report = ScanReport(
        (
            AnalysisResult("a.py", findings=findings[:2]),
            AnalysisResult("b.py", findings=findings[2:]),
        ),
        enabled_rule_count=4,
    )

    html = render_html(report)

    assert "Findings (4)" in html
    assert "Scanned files</span></div>" in html
    assert "Error: 1" in html and "Warning: 2" in html and "Info: 1" in html
    assert all(f'<th scope="row">ML00{i}</th><td>1</td>' in html for i in range(1, 5))


def test_empty_and_partial_reports_do_not_claim_safety() -> None:
    parse_error = AnalysisError(
        AnalysisErrorStage.PARSE,
        NotebookIssueCode.INVALID_JSON,
        "broken.ipynb",
        "Notebook JSON is invalid",
        cell_index=3,
        line=9,
    )
    notice = NotebookIssue(
        NotebookIssueCode.UNSUPPORTED_SYNTAX,
        "partial.ipynb",
        "Magic syntax is unsupported",
        cell_index=2,
        code_cell_index=1,
        line=1,
    )
    report = ScanReport(
        (
            AnalysisResult("broken.ipynb", errors=(parse_error,), analyzed_units=0),
            AnalysisResult("partial.ipynb", notices=(notice,), analyzed_units=2, completed_units=1),
        ),
        scan_notices=(ScanNotice("no_supported_files", "empty", "No supported files found"),),
    )

    html = render_html(report)

    assert "未发现受支持规则能够确认的问题" in html
    assert "这不代表代码绝对安全" in html
    assert "Failed files" in html and "Partial files" in html
    assert "parse / invalid_json" in html
    assert "Notebook notice · unsupported_syntax" in html
    assert "No supported files found" in html
    assert "Parse errors: 1" in html and "Notices: 2" in html


def test_all_untrusted_text_is_escaped_and_report_has_no_active_content() -> None:
    payload = '<script>alert("x")</script><img src=x onerror="bad()">'
    hostile_path = f"reports/{payload}.py"
    finding = Finding(
        "<ML&001>",
        hostile_path,
        1,
        1,
        payload,
        payload,
        payload,
        Evidence.POTENTIAL_STATISTICAL_RISK,
    )
    report = ScanReport(
        (
            AnalysisResult(
                hostile_path,
                findings=(finding,),
                errors=(
                    AnalysisError(
                        AnalysisErrorStage.PARSE,
                        NotebookIssueCode.INVALID_JSON,
                        hostile_path,
                        payload,
                    ),
                ),
            ),
        ),
        scan_notices=(ScanNotice("<notice>", hostile_path, payload),),
    )

    html = render_html(report)
    inspector = StructureInspector()
    inspector.feed(html)

    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=&quot;bad()&quot;&gt;" in html
    assert "<script>alert" not in html
    assert 'onerror="bad()"' not in html
    assert inspector.scripts == 0
    assert inspector.event_attributes == []
    assert inspector.remote_urls == []
    assert "Content-Security-Policy" in html
    assert "<script" not in html


def test_report_is_deterministic_and_uses_no_javascript_or_remote_resources() -> None:
    report = ScanReport(
        (
            AnalysisResult(
                "sample.py",
                findings=(
                    Finding(
                        "ML004", "sample.py", 8, 1, "m", "r", "s", Evidence.CONFIRMED_CODE_PATTERN
                    ),
                    Finding(
                        "ML001",
                        "sample.py",
                        2,
                        1,
                        "m",
                        "r",
                        "s",
                        Evidence.POTENTIAL_STATISTICAL_RISK,
                    ),
                ),
            ),
        )
    )

    first = render_html(report)
    second = render_html(report)

    assert first == second
    findings_section = first.index("<h2>Findings (2)</h2>")
    assert first.index("ML001", findings_section) < first.index("ML004", findings_section)
    assert "<script" not in first.lower()
    assert "http://" not in first and "https://" not in first
    assert "No scan errors or notices." in first
