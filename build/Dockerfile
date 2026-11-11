# Build GeoLite2-City-CN.mmdb in a container.
# NOTE: this Dockerfile has not been run in the build VM (no Docker there);
# build/build.sh is the tested path. If you run this, expect the build to
# take ~5 minutes and ~2 GB of RAM.
FROM golang:1.25.4-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip curl nodejs npm ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY . /build
RUN ./build/build.sh
