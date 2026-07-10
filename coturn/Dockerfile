ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache coturn bash

COPY rootfs /
RUN chmod +x /etc/services.d/coturn/run /etc/services.d/coturn/finish
