# LLM analysis

> **What this is.** Calling an Azure OpenAI chat model from a notebook with LangChain, reading the
> endpoint and key from a secret scope, counting tokens, and driving a structured analysis prompt.
> From a Databricks example notebook; the client's business context and example documents are
> removed, and every scope and key name is a placeholder.

## Create the client from secrets

```python
%pip install langchain langchain_community openai "pydantic==2.7.0"
dbutils.library.restartPython()
```

```python
from langchain.chat_models import AzureChatOpenAI
from langchain_core.messages import HumanMessage
from langchain_community.callbacks.manager import get_openai_callback

llm = AzureChatOpenAI(
    openai_api_base=dbutils.secrets.get("<kv-scope>", "openai-base"),
    openai_api_version=dbutils.secrets.get("<kv-scope>", "openai-version"),
    deployment_name=dbutils.secrets.get("<kv-scope>", "openai-deployment"),
    openai_api_key=dbutils.secrets.get("<kv-scope>", "openai-key"),
    openai_api_type="azure",
    temperature=0.0,  # deterministic for analysis
)
```

> The original notebook also had a second client built from **literal** base and key strings. Delete
> that form — read every value from a secret scope
> ([credential-management](./credential-management.md)).

## A structured analysis function, with token counting

Wrap the call so each invocation returns the text **and** its token cost. Pin `temperature=0` for a
repeatable analysis, and give the prompt a fixed output shape so the result is parseable.

```python
def analyse(text: str) -> tuple[str, dict]:
    prompt = f"""
You are a domain expert. Analyse the content delimited by [start] and [end] and answer in exactly
this shape:

Applicability: <applicable | not applicable>
Reasoning: <concise reasoning>

[start]
{text}
[end]
""".strip()

    with get_openai_callback() as cb:
        reply = llm.invoke([HumanMessage(content=prompt)])

    usage = {
        "prompt_tokens": cb.prompt_tokens,
        "completion_tokens": cb.completion_tokens,
        "total_cost": cb.total_cost,
    }
    return reply.content, usage
```

## Notes

- **Mind the context window.** A single request has a hard token ceiling; split a long document into
  chunks before you send it — see
  [develop-pyspark](../../develop-pyspark/references/chunking-and-embedding-fit.md).
- Keep `temperature=0` for analysis you want to reproduce.
- `get_openai_callback()` gives per-call token counts and cost — log them to catch a prompt that grew.
