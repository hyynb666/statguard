"""Offline HTML report rendering and escaping guarantees."""

import base64
import hashlib
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
        self.script_text: list[str] = []
        self.in_script = False
        self.remote_urls: list[str] = []
        self.event_attributes: list[str] = []
        self.details = 0
        self.open_details = 0
        self.summaries = 0
        self.csp = ""
        self.ids: list[str] = []
        self.progress: list[dict[str, str | None]] = []
        self.finding_attributes: list[dict[str, str | None]] = []
        self.table_rows: list[list[str]] = []
        self._in_rule_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_text = ""
        self._row_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.scripts += 1
            self.in_script = True
        if tag == "details":
            self.details += 1
            if any(name == "open" for name, _ in attrs):
                self.open_details += 1
        if tag == "summary":
            self.summaries += 1
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"] or "")
        if tag == "progress":
            self.progress.append(attributes)
        if tag == "details" and "finding" in (attributes.get("class") or "").split():
            self.finding_attributes.append(attributes)
        if tag == "table" and "rule-table" in (attributes.get("class") or "").split():
            self._in_rule_table = True
        if self._in_rule_table and tag == "tr":
            self._in_row = True
            self._row_text = []
        if self._in_row and tag in {"th", "td"}:
            self._in_cell = True
            self._cell_text = ""
        for name, value in attrs:
            if name.startswith("on"):
                self.event_attributes.append(name)
            if name in {"src", "href"} and value and value.startswith(("http:", "https:")):
                self.remote_urls.append(value)
            if (
                name == "content"
                and value
                and "Content-Security-Policy" in self.get_starttag_text()
            ):
                self.csp = value

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.script_text.append(data)
        if self._in_cell:
            self._cell_text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_script = False
        if self._in_cell and tag in {"th", "td"}:
            self._row_text.append(self._cell_text.strip())
            self._in_cell = False
        if self._in_rule_table and self._in_row and tag == "tr":
            self.table_rows.append(self._row_text)
            self._in_row = False
        if tag == "table" and self._in_rule_table:
            self._in_rule_table = False


def get_rule_rows(html: str) -> list[str]:
    inspector = StructureInspector()
    inspector.feed(html)
    return [row[0] for row in inspector.table_rows[1:]]


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
    assert "Error findings</span>" in html and "Warning findings</span>" in html
    assert "Info findings</span>" in html
    assert get_rule_rows(html) == ["ML001", "ML002", "ML003", "ML004"]
    assert "25.0%" in html and 'id="severity-warning" max="4" value="2">2 of 4</progress>' in html


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

    assert "No issue was confirmed by the enabled rules." in html
    assert "This does not establish that the code is statistically correct" in html
    assert "Failed files" in html and "Partial files" in html
    assert "parse / invalid_json" in html
    assert "Notebook notice · unsupported_syntax" in html
    assert "No supported files found" in html
    assert "Parse errors: 1" in html and "Notices: 2" in html


def test_all_untrusted_text_is_escaped_and_script_is_fixed_and_csp_pinned() -> None:
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
    assert inspector.scripts == 1
    assert inspector.event_attributes == []
    assert inspector.remote_urls == []
    assert inspector.csp.startswith("default-src 'none'; script-src 'sha256-")
    assert "'unsafe-inline'" not in inspector.csp.split("script-src ", 1)[1].split(";", 1)[0]
    script = "".join(inspector.script_text)
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    assert f"script-src 'sha256-{digest}'" in inspector.csp
    assert payload not in script
    assert all(
        token not in script for token in ("innerHTML", "eval(", "Function(", "document.write")
    )
    assert "<script>alert" not in html


def test_report_is_deterministic_and_uses_only_fixed_local_interaction_script() -> None:
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
    findings_section = first.index('<h2 id="findings-heading">Findings (2)</h2>')
    assert first.index("ML001", findings_section) < first.index("ML004", findings_section)
    assert first.count("<script>") == 1
    assert "http://" not in first and "https://" not in first
    assert "innerHTML" not in first and "document.write" not in first
    assert "No scan errors or notices." in first


def test_interactive_controls_reflect_observed_findings_and_keep_details_discoverable() -> None:
    findings = (
        Finding(
            "ML001",
            "path/one.py",
            5,
            2,
            "Leak risk alpha",
            "Risk details alpha",
            "Suggestion alpha",
            Evidence.POTENTIAL_STATISTICAL_RISK,
            severity=Severity.WARNING,
        ),
        Finding(
            "ST002",
            "path/two.py",
            11,
            1,
            "Discarded result beta",
            "Risk details beta",
            "Suggestion beta",
            Evidence.GENERAL_ANALYSIS_ADVICE,
            severity=Severity.INFO,
        ),
    )
    report = ScanReport((AnalysisResult("path/one.py", findings=findings),))

    html = render_html(report)
    inspector = StructureInspector()
    inspector.feed(html)

    assert '<option value="ML001">ML001</option>' in html
    assert '<option value="ST002">ST002</option>' in html
    assert '<option value="warning">warning</option>' in html
    assert '<option value="info">info</option>' in html
    assert 'id="finding-search"' in html
    assert "Showing 2 of 2 findings" in html
    assert "No findings match the current filters." in html
    assert inspector.details == inspector.summaries == 2
    assert inspector.open_details == 0
    assert "Leak risk alpha" in html and "Risk details alpha" in html
    assert "Suggestion beta" in html
    script = "".join(inspector.script_text)
    assert "finding.dataset.rule" in script and "finding.dataset.search" in script
    assert "finding.dataset.file" in script and "finding.dataset.confidence" in script
    assert ".finding-detail" not in script
    assert 'addEventListener("submit"' in script and "preventDefault()" in script
    assert 'id="confidence-filter"' in html and 'id="file-filter"' in html
    assert 'id="expand-visible" type="button">Expand visible' in html
    assert 'id="collapse-visible" type="button">Collapse visible' in html
    assert 'type="reset">Clear filters' in html


def test_empty_findings_render_without_filter_form_but_keep_no_findings_message() -> None:
    html = render_html(ScanReport((AnalysisResult("empty.py"),)))

    assert 'id="finding-filters"' not in html
    assert 'id="finding-search"' not in html
    assert "No findings to filter." in html
    assert "No issue was confirmed by the enabled rules." in html


def test_dashboard_metrics_progress_and_rule_distribution_are_accessible_and_stable() -> None:
    findings = (
        Finding("BETA", "b.py", 1, 1, "b1", "risk", "fix", Evidence.CONFIRMED_CODE_PATTERN),
        Finding("ALPHA", "a.py", 2, 1, "a1", "risk", "fix", Evidence.CONFIRMED_CODE_PATTERN),
        Finding("BETA", "a.py", 3, 1, "b2", "risk", "fix", Evidence.CONFIRMED_CODE_PATTERN),
    )
    error = AnalysisError(
        AnalysisErrorStage.PARSE,
        NotebookIssueCode.INVALID_JSON,
        "broken.ipynb",
        "Invalid notebook",
    )
    report = ScanReport(
        (
            AnalysisResult("a.py", findings=findings[1:]),
            AnalysisResult("b.py", findings=findings[:1]),
            AnalysisResult("broken.ipynb", errors=(error,)),
        ),
        scan_notices=(ScanNotice("empty", ".", "No supported files found"),),
    )

    html = render_html(report)
    inspector = StructureInspector()
    inspector.feed(html)

    normalized_html = " ".join(html.split())
    assert "<strong>3</strong><span>Total findings</span>" in html
    assert "<strong>1</strong> <span>Analysis errors</span>" in normalized_html
    assert "<strong>1</strong><span>Notices</span>" in html
    assert 'id="severity-error" max="3" value="0">0 of 3</progress>' in html
    assert 'id="severity-warning" max="3" value="3">3 of 3</progress>' in html
    assert "Rule overview" in html and "Sorted by finding count, then Rule ID." in html
    assert get_rule_rows(html) == ["BETA", "ALPHA"]
    assert "66.7%" in html and "33.3%" in html
    assert len(inspector.ids) == len(set(inspector.ids))
    assert len(inspector.progress) == 5  # three severities and two represented rules
    assert "File overview" in html and "Error findings" in html and "Errors" in html


def test_finding_filter_metadata_and_search_fields_are_escaped() -> None:
    hostile_path = 'reports/x" data-evil="yes.py'
    hostile_rule = 'CUSTOM"><script>alert(1)</script>'
    finding = Finding(
        hostile_rule,
        hostile_path,
        1,
        1,
        "Message searchable",
        "Risk searchable",
        "Suggestion searchable",
        Evidence.GENERAL_ANALYSIS_ADVICE,
        severity=Severity.INFO,
        confidence=Confidence.MEDIUM,
    )
    html = render_html(ScanReport((AnalysisResult(hostile_path, findings=(finding,)),)))
    inspector = StructureInspector()
    inspector.feed(html)

    assert len(inspector.finding_attributes) == 1
    attrs = inspector.finding_attributes[0]
    assert attrs["data-rule"] == hostile_rule
    assert attrs["data-file"] == hostile_path
    assert attrs["data-severity"] == "info"
    assert attrs["data-confidence"] == "medium"
    search = attrs["data-search"] or ""
    assert all(
        value in search
        for value in (
            "Message searchable",
            "Risk searchable",
            "Suggestion searchable",
            Evidence.GENERAL_ANALYSIS_ADVICE.value,
            "medium",
            hostile_path,
            hostile_rule,
        )
    )
    assert 'data-file="reports/x&quot; data-evil=&quot;yes.py"' in html
    assert 'data-evil="yes"' not in dict(inspector.finding_attributes[0])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_file_and_confidence_filters_list_only_observed_values_in_stable_order() -> None:
    findings = (
        Finding(
            "ML001",
            "z.ipynb",
            5,
            1,
            "z",
            "risk",
            "fix",
            Evidence.POTENTIAL_STATISTICAL_RISK,
            cell=2,
            cell_index=4,
            confidence=Confidence.HIGH,
        ),
        Finding(
            "ST001",
            "a.py",
            3,
            1,
            "a",
            "risk",
            "fix",
            Evidence.POTENTIAL_STATISTICAL_RISK,
            confidence=Confidence.LOW,
        ),
    )
    report = ScanReport(
        (
            AnalysisResult("z.ipynb", findings=(findings[0],)),
            AnalysisResult("a.py", findings=(findings[1],)),
        )
    )
    html = render_html(report)

    assert '<option value="a.py">a.py</option>' in html
    assert html.index('<option value="a.py">a.py</option>') < html.index(
        '<option value="z.ipynb">z.ipynb</option>'
    )
    assert '<option value="high">high</option>' in html
    assert '<option value="low">low</option>' in html
    assert '<option value="medium">medium</option>' not in html
    assert "z.ipynb · cell 4 · line 5, column 1" in html
    assert "cell 2" not in html  # raw-cell index is authoritative for Finding location


def test_dashboard_handles_one_and_many_findings_without_duplicate_ids() -> None:
    one = Finding(
        "ML001", "one.py", 1, 1, "message", "risk", "fix", Evidence.POTENTIAL_STATISTICAL_RISK
    )
    one_html = render_html(ScanReport((AnalysisResult("one.py", findings=(one,)),)))
    one_inspector = StructureInspector()
    one_inspector.feed(one_html)
    assert "100.0%" in one_html
    assert len(one_inspector.finding_attributes) == 1
    assert len(one_inspector.ids) == len(set(one_inspector.ids))

    many = tuple(
        Finding(
            f"R{index % 5:02}",
            f"folder/{index % 7}.py",
            index + 1,
            1,
            f"message {index}",
            "risk",
            "fix",
            Evidence.POTENTIAL_STATISTICAL_RISK,
            confidence=(Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW)[index % 3],
        )
        for index in range(75)
    )
    report = ScanReport((AnalysisResult("many.py", findings=many),))
    many_html = render_html(report)
    many_again = render_html(report)
    many_inspector = StructureInspector()
    many_inspector.feed(many_html)
    assert many_html == many_again
    assert "Findings (75)" in many_html
    assert len(many_inspector.finding_attributes) == 75
    assert len(many_inspector.ids) == len(set(many_inspector.ids))


def test_html_no_js_contract_and_no_remote_or_persistent_behavior() -> None:
    finding = Finding(
        "ML001", "sample.py", 1, 1, "message", "risk", "fix", Evidence.POTENTIAL_STATISTICAL_RISK
    )
    html = render_html(ScanReport((AnalysisResult("sample.py", findings=(finding,)),)))
    inspector = StructureInspector()
    inspector.feed(html)
    script = "".join(inspector.script_text)

    assert '<details class="finding"' in html and "<summary" in html
    assert 'lang="en"' in html
    assert "localStorage" not in html
    assert "sessionStorage" not in html
    assert "document.cookie" not in html
    assert "fetch(" not in script and "XMLHttpRequest" not in script
    assert all(
        forbidden not in script
        for forbidden in (
            "eval(",
            "new Function",
            ".innerHTML",
            ".outerHTML",
            "insertAdjacentHTML",
            "document.write",
            'setTimeout("',
            'setInterval("',
        )
    )
