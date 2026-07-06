ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base-python:3.11-alpine3.19
FROM ${BUILD_FROM}

# GDAL-Systemabhängigkeiten für rasterio
RUN apk add --no-cache \
    gdal \
    gdal-tools \
    gdal-dev \
    geos \
    proj \
    proj-util \
    g++ \
    make

RUN pip3 install --no-cache-dir \
    terracotta[recommended]

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
