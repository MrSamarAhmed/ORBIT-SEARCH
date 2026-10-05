# Tablekeeper — Stage 1 Execution Guide

## Local Toolchain & Execution

```bash
cd stage-1
export PATH="$HOME/.local/bin:$PATH"
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt

# Run tests
.venv/bin/python -m pytest

# Run server
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
```

## Docker Build & Run

```bash
cd stage-1
docker build -t tablekeeper-stage1 .
docker run --rm -p 8080:8080 -e PORT=8080 tablekeeper-stage1
```

## Health Check
```bash
curl http://localhost:8080/health
```
