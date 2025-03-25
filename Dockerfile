FROM python:3.12-slim-bookworm

WORKDIR /artwork-uploader

COPY . /artwork-uploader/

RUN ls

RUN pip install --no-cache-dir -r requirements.txt
# RUN pip install gunicorn

EXPOSE 4567

CMD ["python", "artwork_uploader.py"]