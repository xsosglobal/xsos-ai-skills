# Context Pack Evaluation

## 1. Engineering hard gates

All must pass:

| gate | target |
|---|---:|
| WBS work package resolves | 100% |
| acceptance reference resolves | 100% |
| scenario/capability references resolve | 100% |
| scenario and capability versions match active baseline | 100% |
| pinned source hashes match | 100% |
| same inputs produce the same Context Pack SHA-256 | 100% |
| missing fact is silently guessed | 0 |

Run the automated suite and keep its output as an artifact:

```bash
python3 -m unittest discover -s xsos-context-pack/tests -v
```

## 2. Fault injection

Before accepting a schema or resolver change, deliberately inject each fault and require a non-zero exit:

- delete a referenced capability;
- change a capability or scenario version without updating the baseline;
- retire the active baseline;
- modify a source file pinned by SHA-256;
- delete the WBS acceptance criterion;
- duplicate a scenario or capability ID.

## 3. Claude/Codex consistency test

Give both providers only the same generated Context Pack. Ask the same fixed questions:

1. What is the business goal and completion condition?
2. Which modules/capabilities participate?
3. Which API/data contracts are authoritative?
4. Which files or domains must not be changed?
5. What dependencies and failure paths exist?
6. What evidence is required before completion?

Score 20 atomic facts. Pilot acceptance requires:

- at least 18/20 facts consistent between providers;
- zero conflicting API field, state, permission, or source-of-truth answers;
- zero unsupported facts presented as accepted facts;
- every answer can point to a source path/hash in the pack.

## 4. Real delivery pilot

Run at least three real WBS work packages. Record both the old/manual baseline and Context Pack result:

| metric | definition | first target |
|---|---|---:|
| context preparation time | task start to executor-ready context | -30% |
| clarification interventions | human answers needed after task start | -30% |
| context-caused rework | changes caused by wrong/stale facts | -30% |
| handoff recovery time | new executor to correct project explanation | -30% |
| first-pass gate rate | tasks passing agreed gates without context rework | +20 percentage points |

Do not claim ROI from synthetic fixtures or fewer than three real work packages.

## 5. End condition

A pilot is complete only when:

- engineering hard gates pass;
- consistency thresholds pass;
- the implementation passes project tests and smoke checks;
- the owner approves the scenario and baseline;
- measurement evidence is attached to the Workbench task or WBS handoff.

If the loop keeps editing without reaching these conditions, stop it as `failed` or `needs_owner_decision`; do not let an AI redefine acceptance criteria to finish itself.
