FROM python:3.12-slim

# Install build tools for C extensions (q3huff2 needs gcc)
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy orchestrator Python modules
COPY orchestrator/*.py ./

# Copy tournament package (Anti-Gravity Batch 3)
COPY tournament/ ./tournament/

# Copy bot package + agent runner (for process_manager to spawn bot subprocesses)
COPY bot/ ./bot/
COPY agent_runner.py .
COPY bot/requirements.txt ./bot-requirements.txt
RUN pip install --no-cache-dir -r bot-requirements.txt

# Copy web static files for serving
COPY web/ ./static/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
