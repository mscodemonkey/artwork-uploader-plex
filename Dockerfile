FROM dhi.io/python:3.14.2

WORKDIR /artwork-uploader

COPY . /artwork-uploader

RUN cd /artwork-uploader & \
    pip install -r /artwork-uploader/requirements.txt

EXPOSE 4567

VOLUME /artwork-uploader/bulk_imports

ENTRYPOINT ["python", "/artwork-uploader/artwork_uploader.py"]

CMD ["--debug"]
