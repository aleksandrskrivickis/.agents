# Testing the build and the deploy config

> **Source.** `[repo]` — from a production Databricks project's `tests/unit/bundle/` suite.
> `[deduced]` marks generalisation advice.

Two things break deploys more often than application code: the **wheel** (does it build, and does it
contain what the bundle expects?) and the **bundle config** (does it validate for each target?).
Both are cheap to test and both need to stay out of the default test run, because one shells out to
a build tool and the other needs credentials.

## Custom pytest options for the parts that need more than a laptop

```python
# tests/unit/conftest.py
def pytest_addoption(parser):
    group = parser.getgroup("databricks-bundle")
    group.addoption(
        "--bundle-target",
        choices=["dev", "fiat", "prod"],
        default="dev",
        help="Databricks bundle target for validation (default: dev).",
    )
    group.addoption(
        "--validate-bundle",
        action="store_true",
        help="Run bundle validation using the configured Databricks credentials.",
    )
```

- **`parser.getgroup(...)`** puts your flags under their own heading in `pytest --help` instead of
  scattering them among the built-ins.
- **`choices=[...]`** turns a typo into an argparse error before any test runs — and, usefully,
  documents which targets are safe to point this at. Leave destructive targets out of the list.
- **`action="store_true"` + a skip** is the gate: the test exists, is collected, and reports as
  *skipped* with a reason rather than silently not existing.

```bash
uv run pytest                                                   # fast; bundle tests skip
uv run pytest tests/unit/bundle --validate-bundle --bundle-target dev
```

## Shelling out safely

Both tests invoke an external CLI. The wrapper is small and every argument of it is load-bearing:

```python
import shutil, subprocess
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parents[3]       # repo root from tests/unit/bundle/

def run_command(command):
    executable = shutil.which(command[0])
    assert executable is not None, f"Install {command[0]} and make it available on PATH."
    result = subprocess.run(
        [executable, *command[1:]],
        cwd=BUNDLE_ROOT,
        stdin=subprocess.DEVNULL,       # never let a CLI prompt and hang the run
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",               # a CLI emitting odd bytes must not raise UnicodeDecodeError
        check=False,                    # we assert with a readable message instead
        timeout=1800,
    )
    assert result.returncode == 0, (
        f"{' '.join(command)} failed with exit code {result.returncode}\n"
        f"{result.stdout}\n{result.stderr}"
    )
```

| Argument | Why |
|---|---|
| `shutil.which` + assert | "Install `databricks` and put it on PATH" beats `FileNotFoundError` from deep inside subprocess |
| `cwd=BUNDLE_ROOT` | `databricks bundle` resolves `databricks.yml` from the working directory; pytest's cwd is not reliably the repo root |
| `stdin=subprocess.DEVNULL` | **The one people omit.** A CLI that decides to prompt blocks until the job times out, with no output. Closing stdin turns that into an immediate, legible failure |
| `capture_output` + assert on returncode | `check=True` raises `CalledProcessError`, whose message does not include stdout — so the actual error is invisible |
| `encoding="utf-8", errors="replace"` | Tool output is not guaranteed decodable, especially on Windows |
| `timeout=1800` | Bundle validation against a cold workspace is slow; an unbounded subprocess is an unbounded CI job |
| `parents[3]` | Count it against your own depth, and prefer a marker-file search if the suite moves around `[deduced]` |

## Test the wheel's contents, not just that it built

```python
@pytest.fixture(scope="session")
def built_wheel(tmp_path_factory):
    output_dir = tmp_path_factory.mktemp("bundle-wheel")
    run_command(["uv", "build", "--wheel", "--out-dir", str(output_dir)])

    wheels = list(output_dir.glob("*.whl"))
    assert len(wheels) == 1, f"Expected one built wheel, found {wheels}"

    with ZipFile(wheels[0]) as wheel:
        assert wheel.testzip() is None                      # not corrupt
        names = wheel.namelist()
        assert any(n.startswith("utils/") for n in names), "Wheel does not contain the utils package"
        assert any(n.endswith(".dist-info/METADATA") for n in names), "Wheel is missing package metadata"
        assert any(n.endswith(".dist-info/WHEEL") for n in names), "Wheel is missing wheel metadata"
    return wheels[0]


def test_build_wheel(built_wheel):
    assert built_wheel.is_file()
```

Why each assertion exists:

- **`len(wheels) == 1`** — a stale wheel in the output directory makes "which one did the bundle
  upload?" unanswerable. `tmp_path_factory` gives a clean directory, so more than one means the build
  produced more than one.
- **`testzip()`** — catches a truncated or corrupt archive, which is otherwise discovered on the
  cluster.
- **`startswith("utils/")`** — this is the assertion that earns its keep. A packaging misconfiguration
  (a changed `[tool.hatch.build.targets.wheel] packages`, a renamed source directory, a missing
  `__init__.py`) produces a **valid wheel containing nothing you need**. It builds, it uploads, and the
  pipeline fails at import time on the cluster. Assert your top-level package is in there.
- **`.dist-info/METADATA` and `/WHEEL`** — presence of real package metadata, without pinning a
  version string the pre-commit hook bumps on every commit.

> **Session scope matters.** `uv build` is slow; a function-scoped fixture rebuilds per test. Make it
> `scope="session"` and have the cheap assertions share it.

## Validate the bundle config per target

```python
@pytest.fixture(scope="session")
def validated_bundle(request):
    if not request.config.getoption("--validate-bundle"):
        pytest.skip("Pass --validate-bundle to run authenticated bundle validation.")
    request.getfixturevalue("built_wheel")               # validation needs the artifact present
    target = request.config.getoption("--bundle-target")
    run_command(["databricks", "bundle", "validate", "-t", target])
    return target


def test_validate_bundle(validated_bundle):
    assert validated_bundle in ["dev", "fiat", "prod"]
```

- **`request.getfixturevalue("built_wheel")`** pulls in the wheel fixture *conditionally* — after the
  skip check, so an unflagged run does not pay for a build it will not use. A plain parameter would
  force the build on every run.
- **`bundle validate` is read-only**: it checks schema, duplicate keys, required variables and
  interpolation locally, then authenticates. It deploys nothing.
- **Reaching an authentication error means structural validation already passed**, which makes a
  credential-less local run still useful as a schema check — see
  [databricks-asset-bundles](../../databricks-asset-bundles/SKILL.md).

> **Never let a test deploy.** `bundle validate` only. Not `deploy`, not behind a flag, not "just for
> dev" — a test suite that can mutate a workspace will eventually run against the wrong target. The
> same rule applies to a CI pipeline that runs this suite.

## Where these tests live, and keeping them out of the fast path

```
tests/unit/
├── conftest.py              # pytest_addoption lives here, at the suite root
├── bundle/
│   └── test_databricks-bundle.py
├── pipeline/
└── utils/
```

```bash
uv run pytest                         # everything; bundle validation skips, wheel build runs
uv run pytest tests/unit/pipeline     # skip the bundle folder entirely — no subprocess at all
```

- `pytest_addoption` **must** be in the root `conftest.py` of the collected tree; pytest will not
  pick it up from a subdirectory conftest.
- The wheel build runs by default in the source project, which is a deliberate trade — it is the test
  most likely to catch a packaging regression, and it costs one `uv build`. If that is too slow for a
  pre-commit loop, gate it behind its own flag on the same pattern as `--validate-bundle`.
- In CI, run the default suite on every push and the `--validate-bundle` form only where credentials
  exist. See [test-workflows-devops](../../test-workflows-devops/SKILL.md) /
  [test-workflows-github](../../test-workflows-github/SKILL.md).

## Checklist

1. `pytest_addoption` in the **root** conftest, with `choices` on the target and a `store_true` gate.
2. Skip with a message that names the flag to pass.
3. `shutil.which` assert, `cwd` at the repo root, `stdin=DEVNULL`, explicit encoding, a timeout.
4. Assert the wheel **contains your package** and real metadata — not just that it exists.
5. Session-scoped build fixture; pull it in with `getfixturevalue` after the skip check.
6. `bundle validate` only — never `deploy`.
