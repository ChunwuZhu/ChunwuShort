# TAMU AI API Usage

This project uses the TAMU AI Chat API through the OpenAI-compatible interface.

Sources checked:

- Local Swagger export: `/Users/chunwu/Desktop/Z00LLMConf/A02TAMUAIAPIDoc.md`
- PyPI package docs: https://pypi.org/project/tamu-chat/
- Live model tests with `tamu-chat` package on 2026-05-08

## Recommended Endpoint

Use the OpenAI-compatible base URL:

```text
https://chat-api.tamu.ai/openai
```

For direct HTTP calls, the chat completion endpoint is:

```text
https://chat-api.tamu.ai/openai/chat/completions
```

The older/internal endpoint also works for some models:

```text
https://chat-api.tamu.ai/api/chat/completions
```

Prefer `/openai/chat/completions` for new modules.

## Environment

Store credentials in `.env`; do not hard-code API keys.

```text
TAMU_API_KEY=...
TAMU_API_ENDPOINT=https://chat-api.tamu.ai/openai/chat/completions
TAMU_MODEL=protected.Claude Sonnet 4.6
```

This project currently has two TAMU accounts configured locally:

```text
Primary account:
  key env: TAMU_API_KEY
  base URL: https://chat-api.tamu.ai
  daily credit: $5

Alternate account:
  key env: TAMU_ALT_API_KEY
  base URL: https://tti-api.tamus.ai
  daily credit: $5
```

Do not write either key into repo-tracked files.

The `tamu-chat` package uses these names:

```text
TAMU_CHAT_API_KEY=...
TAMU_CHAT_BASE_URL=https://chat-api.tamu.ai/openai
```

This repo's `llm.tamu_client.TamuChatClient` uses `TAMU_API_KEY` and the full chat endpoint.

## Python Package Usage

The `tamu-chat` package can list models and call chat completions.

```python
from tamu_chat import TAMUChatClient

client = TAMUChatClient(
    api_key="sk-...",
    base_url="https://chat-api.tamu.ai/openai",
)

models = client.list_models()
for model in models:
    print(model["id"])

result = client.chat_completion(
    "Reply exactly OK",
    model="protected.Claude Sonnet 4.6",
)
print(result.text)
```

## Repo Client Usage

Use the local wrapper for project code:

```python
from llm.tamu_client import TamuChatClient

client = TamuChatClient()

text = client.complete([
    {"role": "system", "content": "You are a trading strategy analyst."},
    {"role": "user", "content": "Reply exactly OK"},
])
print(text)
```

The wrapper handles:

- Bearer-token authentication
- OpenAI-style `messages`
- JSON responses
- `text/event-stream` SSE responses
- model fallback
- package-backed model listing through `list_models()`
- Claude temperature normalization: Claude models are sent with `temperature=1` because the TAMU/Bedrock path rejects other temperatures when extended thinking is enabled.

## Chat Request Shape

Direct HTTP request:

```python
import requests

resp = requests.post(
    "https://chat-api.tamu.ai/openai/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": "protected.Claude Sonnet 4.6",
        "messages": [
            {"role": "system", "content": "You are a helpful analyst."},
            {"role": "user", "content": "Reply exactly OK"},
        ],
        "temperature": 0.2,
        "max_tokens": 1000,
    },
    timeout=90,
)
```

For Claude models, use:

```json
{
  "model": "protected.Claude Sonnet 4.6",
  "temperature": 1
}
```

Using `temperature=0` with Claude Sonnet 4.6 returned a Bedrock error during live testing.

The Swagger docs show `/openai/chat/completions` also accepts a query parameter:

```text
bypass_filter=false
```

Keep `bypass_filter=false` unless there is a specific approved reason to change it.

## Available Models

`client.list_models()` returned these primary-account model IDs on 2026-05-08:

```text
protected.o3
protected.Claude Opus 4.1
protected.Claude Opus 4.6
protected.Claude 3.5 Haiku
protected.Claude-Haiku-4.5
protected.Claude Sonnet 4.6
protected.gpt-5.4-nano
protected.Claude Opus 4.5
protected.gemini-2.0-flash
protected.Claude Sonnet 4.5
protected.gpt-5-nano
protected.gemini-2.0-flash-lite
protected.gemini-2.5-pro
protected.text-embedding-3-small
protected.o4-mini
protected.gemini-2.5-flash-lite
protected.Claude Sonnet 4
protected.gpt-4o
protected.gpt-4.1
protected.o3-mini
protected.gpt-5-mini
protected.gemini-2.5-flash
protected.llama3.2
protected.gpt-5
protected.gpt-5.1
protected.gpt-4.1-mini
protected.gpt-4.1-nano
protected.gpt-5.4
protected.gpt-5.4-mini
protected.gpt-5.2
```

The alternate account at `https://tti-api.tamus.ai/openai` returned 32 models:

```text
protected.o4-mini
protected.gemini-2.0-flash
protected.Claude Sonnet 4
protected.Claude 3.5 Sonnet
protected.gemini-2.5-pro
protected.Claude 3.7 Sonnet
protected.o3
protected.gemini-2.5-flash
protected.Claude 3.5 Haiku
protected.text-embedding-3-small
protected.o3-mini
protected.Claude Opus 4.1
protected.gemini-2.0-flash-lite
protected.gpt-4o
protected.llama3.2
protected.gpt-4.1
protected.Claude Sonnet 4.5
protected.gemini-2.5-flash-lite
protected.Claude-Haiku-4.5
protected.gpt-5
protected.Claude Opus 4.5
protected.gpt-5-nano
protected.gpt-5.1
protected.Claude Opus 4.6
protected.gpt-4.1-nano
protected.gpt-4.1-mini
protected.gpt-5-mini
protected.gpt-5.4-nano
protected.Claude Sonnet 4.6
protected.gpt-5.4-mini
protected.gpt-5.4
protected.gpt-5.2
```

Alternate-account smoke test:

- `GET https://tti-api.tamus.ai/openai/models`: OK
- `POST https://tti-api.tamus.ai/openai/chat/completions`: OK with `protected.gpt-4o`
- `POST https://tti-api.tamus.ai/api/chat/completions`: OK with `protected.gpt-4o`
- `POST https://tti-api.tamus.ai/api/v1/chat/completions`: OK with `protected.gpt-4o`

Important naming detail: Claude model IDs use spaces and title case, for example:

```text
protected.Claude Sonnet 4.6
```

These are not valid:

```text
protected.claude-sonnet-4-6
protected.rugo
```

## Live Chat Test Results

Test prompt: `Reply exactly OK`.

Working chat models:

```text
protected.o3
protected.Claude Opus 4.1
protected.Claude Opus 4.6
protected.Claude 3.5 Haiku
protected.Claude-Haiku-4.5
protected.Claude Sonnet 4.6
protected.gpt-5.4-nano
protected.Claude Opus 4.5
protected.gemini-2.0-flash
protected.Claude Sonnet 4.5
protected.gpt-5-nano
protected.gemini-2.0-flash-lite
protected.gemini-2.5-pro
protected.o4-mini
protected.gemini-2.5-flash-lite
protected.Claude Sonnet 4
protected.gpt-4o
protected.gpt-4.1
protected.o3-mini
protected.gpt-5-mini
protected.gemini-2.5-flash
protected.llama3.2
protected.gpt-5
protected.gpt-5.1
protected.gpt-4.1-mini
protected.gpt-4.1-nano
protected.gpt-5.4
protected.gpt-5.4-mini
protected.gpt-5.2
```

Listed but not suitable for chat completion:

```text
protected.text-embedding-3-small
```

## Capability Test Results

Capability tests were run against:

```text
https://chat-api.tamu.ai/openai/chat/completions
```

Tested capabilities:

- Plain chat completion
- `response_format={"type": "json_object"}`
- `response_format={"type": "json_schema", ...}`
- OpenAI-style `tools` and `tool_choice`
- Claude-style explicit `thinking`

Summary:

| Capability | GPT models | Gemini models | Claude Sonnet 4.6 |
| --- | --- | --- | --- |
| Plain chat | Supported | Supported | Supported |
| `response_format=json_object` | Supported | Supported | Failed in test |
| `response_format=json_schema` | Supported | Supported | Failed in test |
| OpenAI-style `tools` / tool calling | Supported | Supported | Failed in test |
| Explicit `thinking` parameter | Not tested / not applicable | Not tested / not applicable | Failed in test |

Models tested successfully with JSON response formats and tool calling:

```text
protected.gpt-5.2
protected.gpt-5.4
protected.gpt-4.1
protected.gemini-2.5-pro
```

For these models:

- `response_format=json_object` returned valid JSON such as `{"ok": true}`.
- `response_format=json_schema` returned valid schema-conforming JSON in the smoke test.
- OpenAI-style `tools` returned `tool_calls` in the SSE response.

Claude Sonnet 4.6 status:

```text
protected.Claude Sonnet 4.6
```

- Plain chat works.
- Advanced OpenAI-compatible controls failed during testing.
- Failures came through the TAMU/LiteLLM/Bedrock path.
- Errors were related to Claude thinking and token/temperature constraints.

Do not rely on `response_format`, `tools`, or explicit `thinking` for Claude Sonnet 4.6 unless retested and confirmed.

## Model Choice Guidance

For the earnings options trading bot, prefer these models when the output will feed a paper-trading or order-planning pipeline:

```text
protected.gpt-5.4
protected.gpt-5.2
protected.gpt-4.1
```

Reasons:

- They support structured JSON output.
- They support OpenAI-style tool calling.
- They work with low temperature settings such as `temperature=0`.

Use Claude Sonnet 4.6 when the goal is high-quality natural-language analysis:

```text
protected.Claude Sonnet 4.6
```

But for Claude:

- Use strict prompting.
- Validate JSON after the response.
- Retry or repair invalid JSON.
- Do not depend on native tool calling or `response_format`.

If a module needs `tool_calls`, extend `llm.tamu_client.TamuChatClient` to return structured tool call deltas from SSE responses. The current wrapper is optimized for text completion and strategy JSON parsing.

## Claude Sonnet 4.6 Notes

Model:

```text
protected.Claude Sonnet 4.6
```

Live tests show that this model works through TAMU, but it has different constraints from the GPT/Gemini models.

Supported:

- Plain text chat completion.
- Extended thinking through the TAMU/Bedrock path.
- Prompt-constrained JSON output.
- `response_format=json_schema` when `max_tokens` is large enough.
- OpenAI-style `tools` with `tool_choice=auto`.

Constraints and caveats:

- `temperature` must be `1`.
- `temperature=0` fails with a Bedrock thinking-mode error.
- If `max_tokens` is provided, it must be greater than the model's thinking budget.
- Small values such as `max_tokens=64`, `128`, or `256` can fail.
- Use at least `max_tokens=2048` for Claude Sonnet 4.6 unless retested.
- Model output can include `<think>...</think>` blocks.
- Client code should strip thinking tags before strict JSON parsing.
- `response_format=json_object` succeeded but returned `{}` in a smoke test; prefer `json_schema`.
- Forced tool calling can fail because thinking mode may not be compatible with forced tool use.
- Use `tool_choice=auto` instead of forcing a specific tool.
- OpenAI-style `image_url` / vision input with a data URL failed with `Could not process image`.

Known-good minimal plain chat request:

```json
{
  "model": "protected.Claude Sonnet 4.6",
  "messages": [
    {"role": "user", "content": "Reply exactly OK"}
  ],
  "temperature": 1
}
```

Known-good explicit thinking request:

```json
{
  "model": "protected.Claude Sonnet 4.6",
  "messages": [
    {"role": "user", "content": "Reply exactly OK"}
  ],
  "temperature": 1,
  "max_tokens": 2048,
  "thinking": {
    "type": "enabled",
    "budget_tokens": 1024
  }
}
```

Known-good JSON schema style:

```json
{
  "model": "protected.Claude Sonnet 4.6",
  "messages": [
    {"role": "user", "content": "Return ok true."}
  ],
  "temperature": 1,
  "max_tokens": 2048,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "OkResult",
      "schema": {
        "type": "object",
        "properties": {
          "ok": {"type": "boolean"}
        },
        "required": ["ok"],
        "additionalProperties": false
      },
      "strict": true
    }
  }
}
```

Known-good tool calling style:

```json
{
  "model": "protected.Claude Sonnet 4.6",
  "messages": [
    {"role": "user", "content": "Call get_weather for College Station."}
  ],
  "temperature": 1,
  "max_tokens": 2048,
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get weather",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {"type": "string"}
          },
          "required": ["city"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

Important implementation detail: tool call arguments are returned as SSE deltas. A client must concatenate partial `tool_calls[].function.arguments` chunks before parsing the final JSON arguments.

## Data Sharing Policy For This Project

For this project, TAMU is treated as a trusted institutional gateway. The trading bots do not need a strict anonymization layer before sending market and strategy context to TAMU.

Allowed to send to the LLM:

- Ticker symbols
- Earnings dates and earnings timing
- Public company data
- News and summaries
- Historical earnings data
- Option chain data
- Stock prices, technical indicators, and volatility data
- User budget and risk preferences
- Existing positions when needed for strategy context
- User market view or trading judgment

Do not send credentials or execution secrets:

- TAMU API keys
- Telegram bot tokens
- Moomoo passwords
- IBKR credentials
- Session files
- Browser profile secrets
- Database passwords unless explicitly needed, which should be avoided

Execution boundary:

- The LLM may generate strategy recommendations and order-plan JSON.
- The LLM must not receive direct broker execution authority.
- Moomoo or IBKR order submission should remain in deterministic project code.
- Before paper or live execution, code should validate budget, max loss, option symbols, quantities, and price limits.

Current design principle:

```text
Market data and decision context may go to the LLM.
Credentials and execution authority stay outside the LLM.
```

## Other API Capabilities

The local Swagger export also lists:

- `GET /openai/models`: list OpenAI-compatible models
- `POST /openai/verify`: verify an API URL/key/config
- `POST /openai/audio/speech`: text-to-speech endpoint
- `/api/v1/files/*`: upload, list, search, read, and process files
- `/api/v1/knowledge/*`: create and manage knowledge collections for RAG-style use
- `/api/v1/chats/*`: internal chat history management
- `/api/v1/models/*`: internal model configuration management

For this repo, start with chat completions only. Use files/knowledge later if a bot needs persistent document retrieval over filings, reports, or research notes.
