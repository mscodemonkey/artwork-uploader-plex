FROM dhi.io/python:3.14.2-dev AS builder

ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

RUN python -m venv /app/venv

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

FROM dhi.io/python:3.14.2

# Copy only runtime code from src/
COPY src/ /app/src/
COPY --from=builder /app/venv /app/venv

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/venv/bin:$PATH"
ENV PYTHONPATH=/app/src:$PYTHONPATH

EXPOSE 4567

# Entry point now in src/
ENTRYPOINT ["python", "/app/src/artwork_uploader.py"]

CMD ["--debug"]
