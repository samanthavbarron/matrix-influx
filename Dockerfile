FROM python:3.13-slim

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY matrix_influx ./matrix_influx/

# Install dependencies and project
RUN pip install --no-cache-dir .

# Create directory for logs
RUN mkdir -p /app/logs

# Run as non-root user
RUN useradd -m matrixuser
RUN chown -R matrixuser:matrixuser /app 
USER matrixuser

CMD ["python", "matrix_influx/matrix_to_influx.py"]
