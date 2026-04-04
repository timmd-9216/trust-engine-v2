# Script Processing: Sentiment Analysis

## Setup

### Ollama (local, recommended on Mac Mini M2)

1. Install Ollama
    run 'ollama serve' to start it
2. Pull a Gemma model


3. ollama list

Examples:

- `ollama pull gemma3:12b`
    ollama pull gemma3:4b # liviano y rápido 3.3GB
- `ollama pull gemma4` (9.6 GB)

1. Verify Ollama is running:

- `curl http://localhost:11434/api/tags`

### Kimi (OpenRouter)

To use Kimi via OpenRouter you must set:

- `OPENROUTER_API_KEY=...`

Optionally:

- `SITE_URL=...`
- `SITE_NAME=...`

## Input formats

### CSV

A CSV with a text column (default `full_text`, fallback `text`).

### JSON

Either:

- A list of objects: `[{...}, {...}]`
- An object with `data` list: `{"data": [{...}, {...}]}`

## Usage

### Ollama + Gemma (default)

```bash
poetry run python -m script_processing.cli --input tweets.csv --output tweets_sent.csv --provider ollama --model gemma3
```

### OpenRouter + Kimi

```bash
export OPENROUTER_API_KEY=... 
poetry run python -m script_processing.cli --input tweets.csv --output tweets_sent.csv --provider openrouter --model moonshotai/kimi-k2:free
```

## Output

Writes a CSV with all original columns plus:

- `sentiment`: `positive` | `neutral` | `negative`
- `confidence`: float between 0 and 1
