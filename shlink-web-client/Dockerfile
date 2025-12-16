
ARG BUILD_FROM
FROM $BUILD_FROM

# Startskript hinzufügen
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Nginx im Vordergrund laufen lassen
CMD ["/run.sh"]
