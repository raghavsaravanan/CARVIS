## Summary

<!-- What changed and why? -->

## Related work

- Issue:
- PRD requirement(s), if applicable:

## Scope

<!-- List the files/systems changed and anything deliberately excluded. -->

Risk tier (`docs/development-workflow.md`, "Risk tiers"): <!-- T1–T4 and the reason; not below the minimum scripts/review-scope.sh reports -->

## Verification

- [ ] Relevant automated tests passed
- [ ] Failure paths were exercised
- [ ] Simulator, physical-device, live-provider, and production checks are labeled separately

Commands and results:

```text

```

## Evidence

<!-- Screenshots, recordings, hardware observations, or N/A with a reason. -->

## Review and workflow record

<!-- The authoritative task record (docs/development-workflow.md). A push after the reviewed
candidate makes its reviews stale. -->

- Base SHA (effective base after any update from main):
- Reviewed candidate SHA:
- Reviews (reviewer, model where reported, SHA, verdict, findings fixed/open):
- Mutation checks (guard disabled → failing test):
- Final drift check against `origin/main`:
- Duration, human interventions, review iterations, CI failures, rework commits, integration conflicts:
- Agents and models (where reported; token counts are not reliably available):

## Risk review

- Security/privacy implications:
- Database or migration implications:
- Provider/API contract changes:
- Secrets or local-data handling:

## Rollback

<!-- How can this change be disabled or reverted safely? -->

## Completion checklist

- [ ] Existing iPhone/Vapi/FastAPI/Qdrant behavior is preserved or intentionally migrated
- [ ] Vehicle applicability and evidence/refusal boundaries remain intact
- [ ] No credentials, manuals, local databases, captures, or customer data were committed
- [ ] Documentation and API contracts were updated where required
- [ ] No production service, provider configuration, Qdrant alias, or database was mutated without approval
