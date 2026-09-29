## Summary

<!-- What changed and why? -->

## Related issue

<!-- Link the issue. -->

## Behavior and evidence

- User-visible behavior change:
- Statistical/evidence rationale:
- False-positive review and cases where analysis abstains:

## Validation

- [ ] Positive, negative, and boundary tests added or updated
- [ ] `python -m pytest`
- [ ] `python -m ruff check .`
- [ ] `python -m ruff format --check .`
- [ ] `python -m build` (when packaging or release files change)
- [ ] Documentation updated

## Safety and compatibility

- [ ] No submitted Python or Notebook code is executed
- [ ] Notebook outputs are not analyzed
- [ ] Rule source identity is resolved; no variable-name-only inference
- [ ] Unknown cases abstain rather than guessing
- [ ] Existing rule/API/JSON behavior remains compatible or changes are documented

## Rule-specific review (complete for rule changes)

- [ ] Supported source identity and data lineage are explicit
- [ ] Positive, negative, boundary, and known-limitations cases are covered
- [ ] Finding evidence category, location, wording, and recommendation are reviewed
