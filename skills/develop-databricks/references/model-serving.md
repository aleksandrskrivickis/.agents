# Model serving

> **What this is.** Logging a custom MLflow `pyfunc` model with a typed signature, registering it,
> and calling its serving endpoint. From a Databricks example notebook (an iris classifier); the
> workspace URL and token are placeholders. The source folder also holds a text-classifier and a
> logistic-regression example that follow the same log → register → serve shape.

## Wrap a model in a pyfunc with a typed signature

A `pyfunc` wrapper lets you shape the serving output — here, class probabilities plus a label.

```python
import mlflow, mlflow.pyfunc, pandas as pd
from sklearn import datasets
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from mlflow.models.signature import ModelSignature
from mlflow.types.schema import Schema, ColSpec


class ModelWrapper(mlflow.pyfunc.PythonModel):
    def __init__(self, model):
        self.model = model

    def predict(self, context, model_input):
        labels = ["setosa", "versicolor", "virginica"]
        probs = self.model.predict_proba(model_input)
        preds = self.model.predict(model_input)
        result = pd.DataFrame(probs, columns=[f"prob_{l}" for l in labels])
        result["prediction"] = [labels[p] for p in preds]
        return result


iris = datasets.load_iris()
X_tr, X_te, y_tr, y_te = train_test_split(iris.data, iris.target, test_size=0.3, random_state=42)
rf = RandomForestClassifier(random_state=42).fit(X_tr, y_tr)

input_schema = Schema([ColSpec("double", n) for n in iris.feature_names])
output_schema = Schema([ColSpec("double", f"prob_{s}") for s in iris.target_names] + [ColSpec("string", "prediction")])
signature = ModelSignature(inputs=input_schema, outputs=output_schema)

with mlflow.start_run():
    mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model=ModelWrapper(rf),
        signature=signature,
        input_example=pd.DataFrame(X_tr[:1], columns=iris.feature_names).to_dict(orient="list"),
        registered_model_name="my-model",
    )
```

## Call the serving endpoint

Create the endpoint in **Serving** from the registered model version, then invoke it:

```bash
curl --location 'https://<workspace-url>/serving-endpoints/my-model/invocations' \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer <token>' \
  --data '{
    "dataframe_records": [
      {"sepal length (cm)": 5.1, "sepal width (cm)": 3.5, "petal length (cm)": 1.4, "petal width (cm)": 0.2}
    ]
  }'
```

## A string-in, string-out passthrough model

The source folder also logs a trivial `pyfunc` whose `predict` returns its input. It is the smallest
shape that still exercises a text signature and the serving path — useful to test an endpoint end to
end.

```python
class ModelWrapper(mlflow.pyfunc.PythonModel):
    def predict(self, context, model_input):
        return model_input


input_schema = Schema([ColSpec("string", "text")])
output_schema = Schema([ColSpec("string", "text")])
signature = ModelSignature(inputs=input_schema, outputs=output_schema)

with mlflow.start_run():
    mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model=ModelWrapper(),
        input_example={"text": "Quick brown fox"},
        signature=signature,
        registered_model_name="text-model",
    )
```

## Fronting the endpoint with Azure API Management (optional)

A serving endpoint accepts **POST only**, with the payload in the body and a bearer token in the
header. Some callers (for example the Excel `WEBSERVICE` function) can send only a `GET` with query
string. To bridge that, put Azure API Management (APIM) in front of the endpoint and map a `GET`
query parameter to the required POST body:

```
https://<apim-host>/databricks/serving-endpoints/my-model/invocations?text=Quick%20brown%20fox
```

APIM holds the bearer token, sets `Content-Type: application/json`, and builds the
`{"dataframe_records": [...]}` body with a set-body policy. The caller sends a plain URL.

## Notes

- The typed `ModelSignature` makes the endpoint validate inputs and document outputs.
- A `pyfunc` wrapper is how you return probabilities **and** a label, or any shaped response.
- For serving at scale (batching, concurrency, request size, retries), see
  [develop-pyspark](../../develop-pyspark/SKILL.md).
