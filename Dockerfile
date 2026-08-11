FROM python:3.13-slim

# Prevents Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy uv binary from official image for fast installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

# Create Data directory for temporary file processing
RUN mkdir -p /app/Data

# Copy application source code into the container
COPY . .

EXPOSE 2500

CMD ["python", "app/main.py"]
