"""Parse explicit, source-local Finding suppression comments without execution."""

from __future__ import annotations

import io
import re
import tokenize
from dataclasses import dataclass

_DIRECTIVE = re.compile(
    r"#\s*statguard:\s*(?P<mode>ignore-next-line|ignore)\s+"
    r"(?P<ids>[A-Za-z][A-Za-z0-9_-]*(?:\s*,\s*[A-Za-z][A-Za-z0-9_-]*)*)\s*"
)


@dataclass(frozen=True, slots=True)
class SuppressionIndex:
    """Immutable pairs of physical source line and exact rule ID to suppress."""

    entries: frozenset[tuple[int, str]] = frozenset()

    @classmethod
    def from_source(cls, source: str) -> SuppressionIndex:
        """Index valid directives found only in Python COMMENT tokens.

        Tokenization is all-or-nothing: malformed source never uses a partial
        directive index. Python syntax parsing normally rejects such input
        before Analyzer reaches this method, but the method remains safe alone.
        """
        entries: set[tuple[int, str]] = set()
        try:
            tokens = tokenize.generate_tokens(io.StringIO(source).readline)
            for token in tokens:
                if token.type != tokenize.COMMENT:
                    continue
                match = _DIRECTIVE.fullmatch(token.string)
                if match is None:
                    continue
                rule_ids = tuple(part.strip() for part in match.group("ids").split(","))
                # Reject wildcard-like and conventional blanket sentinels.
                if any(rule_id == "*" or rule_id.upper() == "ALL" for rule_id in rule_ids):
                    continue
                line = token.start[0]
                if match.group("mode") == "ignore-next-line":
                    line += 1
                entries.update((line, rule_id) for rule_id in rule_ids)
        except (IndentationError, SyntaxError, tokenize.TokenError, UnicodeError):
            return cls()
        return cls(frozenset(entries))

    def suppresses(self, *, line: int, rule_id: str) -> bool:
        """Return whether this exact rule ID is suppressed at this line."""
        return (line, rule_id) in self.entries
