# XSOS Business Context Contract v0.1

## Layout

```text
business-context/
  capabilities/*.yaml
  scenarios/*.yaml
  baselines/*.yaml
```

Facts remain in their owning repositories. These files contain identifiers, versions, composition, and source references.

## Capability

```yaml
id: drawing.read
version: 1.0.0
status: active
domain: drawing
owner: gallery-owner
description: Read an approved drawing.
contract_refs:
  - docs/wbs/04-api-contract.md
source_refs:
  - module.yaml
  - repo: xsos-pda
    path: docs/wbs/04-api-contract.md
```

Required: `id`, `version`, `status=active`, `domain`, `owner`.

## Scenario

```yaml
id: production-order-release
version: 1.0.0
status: accepted
owner: production-owner
goal: Release a production order with the approved drawing and routing.
trigger: A reviewed order is ready for release.
outcome: The order is released with traceable inputs.
participants:
  - capability_id: drawing.read
    required_version: 1.0.0
steps:
  - Load the approved drawing.
acceptance_refs:
  - AC-BE-001
source_refs:
  - docs/wbs/01-requirements.md
```

Required: `id`, `version`, `status=accepted`, `owner`, `goal`, and at least one participant.

## Baseline

```yaml
id: baseline-2026-07-27
mode: formal
status: active
approved_by: tech-owner
approved_at: 2026-07-27
approval_ref: approvals/2026-07-27-delivery-pmi.md
scenario_versions:
  production-order-release: 1.0.0
capability_versions:
  drawing.read: 1.0.0
source_hashes:
  docs/wbs/01-requirements.md: <sha256>
  xsos-pda:docs/wbs/04-api-contract.md: <sha256>
repository_revisions:
  project: <full-git-commit>
  xsos-pda: <full-git-commit>
```

Required: `id`, `status=active`, `approved_by`, `approved_at`, selected scenario version, and every participant capability version.

`mode=draft` may omit approval evidence and repository revisions. `mode=formal` requires an existing, repository-local `approval_ref` plus an exact Git revision for every referenced project repository. Approval evidence is included in the generated source manifest and hash. `source_hashes` pins selected high-value facts. A changed revision or hash is a blocking error.

Additional repositories are supplied explicitly; they are never discovered by walking parent directories:

```bash
--repo xsos-pda=/absolute/path/to/xsos-pda
```

References may use `{repo, path}` objects or `repo:path` strings. Paths must stay inside an allowed repository. Absolute paths, `..`, symlink escapes, `.env*`, credentials, secrets and token files are rejected.

## Validation failures

The validator must fail for:

- missing WBS work package or acceptance criterion;
- missing scenario, capability, or baseline;
- scenario not accepted or baseline not active;
- duplicate IDs;
- unpinned or mismatched versions;
- missing referenced project files;
- source hash drift.
- formal baseline without approval evidence or exact repository revisions;
- unknown repository alias, path escape, or sensitive source reference.
