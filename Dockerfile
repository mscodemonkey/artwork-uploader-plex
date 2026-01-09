FROM python:3.14.2-slim

ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:${PATH}"
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

COPY requirements.txt .

COPY src/ /app/src/

COPY entrypoint.sh /entrypoint.sh

# Install gosu for dropping privileges and set up Python environment
RUN apt-get update && \
    apt-get install -y --no-install-recommends gosu && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    python -m venv /app/venv && \
    pip install --no-cache-dir -r requirements.txt && \
    chmod +x /entrypoint.sh

EXPOSE 4567

# Use entrypoint script to handle PUID/PGID at runtime
ENTRYPOINT ["/entrypoint.sh"]

CMD ["python", "/app/src/artwork_uploader.py", "--debug"]
