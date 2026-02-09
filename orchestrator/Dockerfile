FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy orchestrator Python modules
COPY orchestrator/*.py ./

# Copy tournament package (Anti-Gravity Batch 3)
COPY tournament/ ./tournament/

# Copy web static files for serving
COPY web/ ./static/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
