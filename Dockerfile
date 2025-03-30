FROM python:3.10

WORKDIR /app

COPY . /app

RUN cd /app & \
    pip install -r /app/requirements.txt

VOLUME /app/data
EXPOSE 4567

CMD [ "python",  "/app/artwork_uploader.py" ]