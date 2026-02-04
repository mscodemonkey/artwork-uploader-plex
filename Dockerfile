FROM python:3.14.3

ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:${PATH}"
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

COPY requirements.txt .

COPY src/ /app/src/

COPY entrypoint.sh /entrypoint.sh

# Install gosu for dropping privileges and create necessary directories
RUN apt-get update && \
    apt-get install -y --no-install-recommends gosu && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    python -m venv /app/venv && \
    pip install --no-cache-dir -r requirements.txt && \
    chmod +x /entrypoint.sh && \
    groupadd -g 1027 artwork && \
    useradd -u 1027 -g artwork -m artwork

EXPOSE 4567

USER artwork

ENTRYPOINT ["python", "/app/src/artwork_uploader.py"]

CMD ["--debug"]

