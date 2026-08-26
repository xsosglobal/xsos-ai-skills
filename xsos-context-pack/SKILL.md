---
name: xsos-context-pack
description: Build and validate an XSOS task Context Pack from project WBS, a global business scenario, domain capability declarations, and an active baseline. Use when Claude, Codex, or a teammate needs the same traceable task context; when checking missing capability references, version drift, stale source hashes, WBS acceptance references, or cross-project context consistency.
---

# XSOS Context Pack

Keep facts in their owning repositories. Use this skill only to resolve, validate, and assemble them.

## Workflow

1. Read the target project's `AGENTS.md`, standards, and `docs/wbs`.
2. Read `references/context-contract.md` when creating or changing business-context files.
   Read `references/evaluation.md` when accepting a pilot or claiming efficiency improvement.
3. Validate before building:

```bash
python3 scripts/context_pack.py validate \
  --project-root <project> --wp <WP-ID> \
  --context-root <business-context> \
  --scenario <scenario-id> --baseline <baseline-id> \
  [--repo <alias>=<absolute-repository-path> ...]
```

4. Stop when validation fails. Do not silently select another version or invent a missing fact.
5. Build the pack only after validation passes:

```bash
python3 scripts/context_pack.py build \
  --project-root <project> --wp <WP-ID> \
  --context-root <business-context> \
  --scenario <scenario-id> --baseline <baseline-id> \
  [--repo <alias>=<absolute-repository-path> ...] \
  --output <context-pack.md>
```

6. Give every parallel executor the same generated pack and record its SHA-256.
7. Treat generated packs as artifacts, not new sources of truth. Regenerate after any source change.

## Hard boundaries

- Project repositories own WBS, contracts, code, and evidence.
- Domain/module repositories own capability facts.
- The business-context repository owns cross-domain scenarios and active baselines.
- Skills own procedures; they do not own business facts.
- Workbench may call this skill, but must not become the only way to generate a pack.
- Human owners approve scenarios and baselines. AI may validate them but must not self-approve them.
- A formal baseline pins every referenced repository to an exact Git commit and records human approval evidence.
- Source paths are allowlisted by repository alias; path escapes and sensitive files are blocking errors.

## Required result

Report:

- selected scenario and baseline versions;
- resolved capabilities;
- WBS and acceptance references;
- source paths and hashes;
- validation errors, without downgrading them to warnings.
