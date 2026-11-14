ARG BUILD_FROM
FROM ${BUILD_FROM}
# python3 + numpy für Show und Audioanalyse; shairport-sync als AirPlay-Empfänger,
# avahi + dbus, damit Music Assistant den Empfänger per mDNS findet
RUN apk add --no-cache python3 py3-numpy shairport-sync avahi dbus
WORKDIR /app
COPY app/ /app/
COPY run.sh /run.sh
RUN chmod a+x /run.sh
CMD ["/run.sh"]
