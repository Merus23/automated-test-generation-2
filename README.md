# automated-test-generation-2

## Docker compose commands

Create the environment

```bash
docker-compose up --build
```

Find the container ID

```bash
docker ps -a
```

Run to execute the experiment into the isolated environment

```bash
docker exec -it <container_id_ou_nome> /bin/bash
```

## CLI Usage

All commands are executed through `run.py`.

### Inline example (no external codebase needed)

```bash
python run.py example
```

### Extract prompt for a specific method

```bash
python run.py extract --base /path/to/sf110 --class MyClass --method myMethod --junit "JUnit 5" --output prompt.txt
```

Use `--prompt-type` to select the prompt strategy (default: `zero_shot`):

```bash
python run.py extract --base /path/to/sf110 --class MyClass --method myMethod --prompt-type zero_shot
```

### Extract prompts in batch

```bash
python run.py batch --base /path/to/sf110 --output-dir output --max 100
```

Use `--prompt-type` to apply a specific prompt strategy to all extracted prompts:

```bash
python run.py batch --base /path/to/sf110 --output-dir output --max 100 --prompt-type zero_shot
```

#### Available prompt types

| Type | Description |
|------|-------------|
| `zero_shot` | Structured prompt with class declaration, focal method, helper signatures, dependent classes, and generation instructions |

### Download a model from Hugging Face

```bash
python run.py download --model-id Qwen/Qwen3-0.5B
```

### Generate test from a single prompt

```bash
python run.py generate --model Qwen_Qwen3-0.5B --prompt output/0007_DocumentSet_wordFrequency.txt --output test.java
```

### Generate tests in batch

```bash
python run.py generate-batch --model Qwen_Qwen3-0.5B --input-dir output --output-dir generated_tests --max 10
```
