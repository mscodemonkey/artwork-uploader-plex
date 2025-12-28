APP=artwork-uploader-plex
REGISTRY=jabrown
TAG ?= $(shell git describe --tags --always --dirty)
PLATFORMS=linux/amd64,linux/arm64

.PHONY: docker-build docker-release

docker-build:
	docker buildx build \
	  --platform=$(PLATFORMS) \
	  -t $(REGISTRY)/$(APP):$(TAG) \
	  -t $(REGISTRY)/$(APP):dev \
	  .

docker-release:
	docker buildx build \
	  --platform=$(PLATFORMS) \
	  -t $(REGISTRY)/$(APP):$(TAG) \
	  -t $(REGISTRY)/$(APP):dev \
	  --push \
	  .
