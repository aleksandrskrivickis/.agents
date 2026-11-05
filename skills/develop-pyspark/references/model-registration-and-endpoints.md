# Registering a model and standing up its serving endpoint

> **Source.** `[repo]` — from a production job that registers a sentence-embedding model into Unity
> Catalog and creates/updates its serving endpoint idempotently, plus the decisions and findings
> recorded against it. `[docs]` marks a documented Databricks/MLflow constraint; `[deduced]` an
> inference.

[model-serving-and-batching.md](./model-serving-and-batching.md) covers **calling** an endpoint from
Spark. This file covers the other side: producing the endpoint, and the preconditions the calling
stage silently depends on.

## The shape

One notebook/job, run once per deploy, doing five things in order:

```
1. wrap the model          mlflow.pyfunc.PythonModel + artifacts
2. decide if it changed    signature tag vs registered versions  → skip if identical
3. register                mlflow.pyfunc.log_model(registered_model_name=<UC 3-part name>)
4. validate locally        validate_serving_input + load_model().predict()
5. create or update        w.serving_endpoints.create_and_wait / update_config_and_wait
```

Steps 2 and 4 are what make it safe to run on every deploy. Without them it is either destructive
or slow.

## Wrap the model in a `pyfunc` with an explicit response shape

```python
class OpenAIStyleEmbedder(mlflow.pyfunc.PythonModel):
    version = "1"                      # bump to force re-registration on a wrapper change

    def load_context(self, context):
        self.model = SentenceTransformer(context.artifacts["repository"])

    def _texts(self, model_input):
        if isinstance(model_input, pd.DataFrame):
            values = model_input.iloc[:, 0].tolist()
        elif isinstance(model_input, dict):
            values = model_input.get("input", model_input.get("inputs", []))
        else:
            values = model_input
        if len(values) == 1 and isinstance(values[0], (list, tuple)):
            values = values[0]
        return [str(x) for x in values]

    def predict(self, context, model_input, params=None):
        vectors = self.model.encode(self._texts(model_input), normalize_embeddings=True)
        return {"data": [{"index": i, "embedding": v.tolist()} for i, v in enumerate(vectors)]}
```

- **`artifacts={"repository": local_path}` + `load_context`** is how you ship model weights that are
  not a pip install. Save the model to a local path first (`SentenceTransformer(src).save(path)`),
  then log that path as an artifact; `load_context` runs once per replica on startup, not per
  request. Loading in `predict` instead is the classic cold-path mistake.
- **`_texts` is defensive on purpose.** Serving sends a pandas DataFrame, `mlflow.deployments`
  sends a dict, a local `predict` may get a list, and a single-element list-of-lists arrives when a
  caller nests. Normalising all four in one place beats debugging a shape error inside a replica.
- **The `{"data": [{"index", "embedding"}]}` response shape is the OpenAI embeddings contract.**
  Returning it means callers written against OpenAI-style clients work unchanged.
- `normalize_embeddings=True` at encode time means consumers can use a dot product as cosine
  similarity. Decide this once, here — not in every consumer.
- **`version` as a class attribute** is the handle for step 2: a change to the wrapper logic that
  does not change the source model still needs a new registered version, and nothing else would
  detect it. `[deduced]`

### Declare the task so serving knows what it is

```python
mlflow.pyfunc.log_model(
    name="model",
    python_model=OpenAIStyleEmbedder(),
    artifacts={"repository": local_path},
    input_example={"input": ["example sentence to embed"]},
    metadata={"task": "llm/v1/embeddings"},
    pip_requirements=["sentence-transformers==5.5.1"],
    registered_model_name=f"{catalog}.{schema}.{model_name}",     # UC 3-part name
)
```

- **`metadata={"task": "llm/v1/embeddings"}`** is what makes the endpoint expose the OpenAI-compatible
  route. Omit it and you get a generic pyfunc endpoint that clients must special-case. `[docs]`
- **`pip_requirements` pins the serving environment.** Let MLflow infer them and a future resolution
  can change the model's behaviour. Pin the libraries that affect the numbers.
- **`registered_model_name` must be the Unity Catalog three-part name.** Registering to the workspace
  registry instead is a different namespace, and the endpoint will not find it.
- `input_example` is not decoration — step 4 needs it.

## Make registration idempotent with a signature tag

Re-registering on every deploy creates a new version each time and forces an endpoint update, which
is slow and loses the ability to say "nothing changed". Compute an identity for *what you are about
to register*, tag the version with it, and look for it first.

```python
model_signature = f"{OpenAIStyleEmbedder.version}-{model_name}"

matching = [
    int(v.version)
    for v in client.search_model_versions(f"name='{uc_model_name}'")
    if client.get_model_version(uc_model_name, v.version).tags.get("model_signature") == model_signature
]

if matching:
    target_version = max(matching)
    print(f"Identical model already registered as version {target_version}; skipping registration.")
else:
    ...  # log_model as above
    target_version = max(int(v.version) for v in client.search_model_versions(f"name='{uc_model_name}'"))
    client.set_model_version_tag(uc_model_name, str(target_version), "model_signature", model_signature)
```

- **The signature must cover every input that changes behaviour** — wrapper version, source model,
  and any preprocessing constant. A signature that omits one leaves the version unchanged when it
  should have moved: the exact failure this exists to prevent, arriving through the back door.
- This is the same idea as the generation stamps in
  [chunking-and-embedding-fit.md](./chunking-and-embedding-fit.md): a derived artifact carries the
  identity of the method that produced it. Build the signature from a single config object that the
  model also reads, and assert its key set in a test.
- **The tag is set *after* `log_model`**, so a crash between them leaves an untagged version that the
  next run will not match — it will register again. Tolerable (a duplicate version) but worth
  knowing. `[deduced]`

## Validate before deploying

```python
model_uri = f"models:/{uc_model_name}/{target_version}"

serving_payload = convert_input_example_to_serving_input({"input": example_sentences})
validate_serving_input(model_uri, serving_payload)          # fails here, not in the replica

print(mlflow.pyfunc.load_model(model_uri).predict({"input": example_sentences}))
```

`validate_serving_input` runs the model through the **serving** code path locally. A payload the
wrapper mishandles fails in the job, in seconds, with a stack trace — instead of surfacing as a 500
from a replica twenty minutes into a `create_and_wait`. Always include it. `[docs]`

## Create or update the endpoint, idempotently

```python
served_entity = ServedEntityInput(
    name=model_name,
    entity_name=uc_model_name,
    entity_version=str(target_version),
    # Static lookup model; CPU is enough and avoids GPU cold-start/scarcity stalls.
    workload_type=ServingModelWorkloadType.CPU,
    # Custom scale-out replaces workload_size: keep a warm floor so there is no scale-from-zero latency.
    min_provisioned_concurrency=4,
    max_provisioned_concurrency=32,
    scale_to_zero_enabled=False,
)
traffic_config = TrafficConfig(routes=[Route(served_model_name=model_name, traffic_percentage=100)])

existing = {e.name for e in w.serving_endpoints.list()}

def already_serving_target(name):
    if name not in existing:
        return False
    served = (w.serving_endpoints.get(name).config or {}).served_entities or []
    return any(e.entity_name == uc_model_name and e.entity_version == str(target_version) for e in served)

if already_serving_target(model_name):
    print("already serves this version; skipping")
elif model_name in existing:
    w.serving_endpoints.update_config_and_wait(
        name=model_name, served_entities=[served_entity],
        traffic_config=traffic_config, timeout=timedelta(hours=1))
else:
    w.serving_endpoints.create_and_wait(
        name=model_name,
        config=EndpointCoreConfigInput(name=model_name, served_entities=[served_entity],
                                       traffic_config=traffic_config),
        timeout=timedelta(hours=1))
```

### Sizing: `min/max_provisioned_concurrency` instead of `workload_size`

| Knob | What it does | When |
|---|---|---|
| `workload_size: Small/Medium/Large` | Preset concurrency bands (`Small` serves 0–4 concurrent callers) | Simple cases; still widely referenced in docs and examples |
| `min_provisioned_concurrency` / `max_provisioned_concurrency` | Explicit scale-out floor and ceiling | When you need a warm floor, or a ceiling the presets don't offer |
| `scale_to_zero_enabled` | Idles to zero replicas | Cost-saving on bursty, latency-tolerant workloads |

- **The floor is the latency decision.** `scale_to_zero_enabled=False` with
  `min_provisioned_concurrency=4` means no scale-from-zero cold start — which for a Spark stage that
  fans out to the endpoint is the difference between a fast run and a run whose first micro-batch
  times out. It also means you pay continuously; that is the trade.
- **`workload_type=CPU` is a real choice, not a default.** For a static lookup/embedding model, GPU
  buys little and exposes you to GPU cold-start and capacity stalls. Record why you picked it.
- **Whatever the endpoint's concurrency is, the calling stage must match it.** See
  [model-serving-and-batching.md](./model-serving-and-batching.md): the caller's
  `shuffle.partitions`, `default.parallelism` **and** an explicit `.repartition(n)` all need that
  number, and only the repartition guarantees fan-out. These two files must agree; if you change the
  endpoint's concurrency here, the pipeline's constant is a second edit.
- `timeout=timedelta(hours=1)` on both waits — endpoint provisioning genuinely takes tens of
  minutes, and the SDK default is shorter.

## The preconditions a calling stage depends on

These are the failure modes that bite *elsewhere* when this job has not run:

1. **Serving-endpoint names are workspace-global.** An endpoint created by any target is visible to
   all of them. That is convenient and dangerous: a pipeline in one environment can be reading an
   endpoint another environment deployed, with no declared dependency. See
   [databricks-asset-bundles](../../databricks-asset-bundles/SKILL.md) for why a stable endpoint name
   must be deployed from a production-mode target.
2. **If the registration job lives in only one target, the others silently rely on it.** In the
   source project the endpoint declarations sat inside one target only; neither of the two
   environments that *used* the endpoint created it, and nothing checked. Run
   `databricks serving-endpoints list` before changing the endpoint name a pipeline resolves.
3. **Resolving the endpoint on the driver at module scope fails the whole update**, not just the
   embedding stage, when the name does not exist. That is the *safer* failure — a loud one — and is
   worth choosing deliberately over a lazy lookup that fails per-task. `[repo]`
4. **The model's context window is a correctness constraint, not a performance one.** A model whose
   window is shorter than your inputs truncates **silently** and every output looks correct. This is
   the single most expensive mistake in this area — see
   [chunking-and-embedding-fit.md](./chunking-and-embedding-fit.md).
5. **Model generations accumulate.** Keying the consuming stage's append flow on the model name
   means a model swap writes a new generation beside the old rows instead of corrupting comparisons
   — no full refresh needed. The cost is a full corpus copy per model tried, and a table that can
   hold vectors of differing dimensionality, so every reader must filter to one model. Decide a
   retention policy when you adopt the pattern.

## Don't

- Don't `log_model` on every run without a signature check — it churns versions and endpoint updates.
- Don't skip `validate_serving_input` because the local `predict` worked; they are different paths.
- Don't infer `pip_requirements` for a model whose numbers you compare across runs.
- Don't let the endpoint's concurrency and the caller's repartition drift apart.
- Don't create an endpoint from a development-mode bundle target if its name must be stable —
  the name gets prefixed, and the name is workspace-global.
