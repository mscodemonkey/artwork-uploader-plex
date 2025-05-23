FROM python:3.12-slim-bookworm

WORKDIR /artwork-uploader

COPY . /artwork-uploader/

RUN ls

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 4567

VOLUME /artwork-uploader/bulk_imports

CMD ["python", "artwork_uploader.py"]