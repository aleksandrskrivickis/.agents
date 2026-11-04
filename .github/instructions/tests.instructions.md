---
applyTo: "src/**,tests/**"
---

When generating or maintaining tests, follow the **`test-python`** skill (pytest layout, `test_`
naming, mocking, the non-importable-module harness, running with `uv`). For the CI that runs them,
use **`test-workflows-github`** (GitHub Actions) or **`test-workflows-devops`** (Azure DevOps).

Essentials to honour even without loading a skill (GitHub's reviewer/cloud-agent reads this file but
scans skills only from `.github/skills/`, so the rules below must stand alone):

- `tests/unit/` mirrors `src/`; `test_<module>.py` preserving hyphens and stage numbers; no
  `python_files` override.
- Mock external I/O; don't import notebook/pipeline modules — test their pure helpers via a harness.
- Keep `test_integration_*` tests skippable when their runtime (e.g. a JDK) is absent.
