FROM python:3.14-slim-bookworm

# Prevent Python from writing .pyc files and buffer logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /artwork-uploader

# Copy only requirements first for better layer caching
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose web UI port
EXPOSE 4567

# Declare volume for bulk imports
VOLUME ["/artwork-uploader/bulk_imports"]

# Health check configuration
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; exit(0 if urllib.request.urlopen('http://localhost:4567/api/health').getcode() == 200 else 1)"

# Run application
ENTRYPOINT ["python", "artwork_uploader.py"]
