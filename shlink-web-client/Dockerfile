
# /addons/shlink-web-client/Dockerfile
FROM shlinkio/shlink-web-client:stable

# Minimal-Tools für das Startskript
RUN apk add --no-cache bash jq tzdata

# Startskript einbinden
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8080
CMD ["/run.sh"]
``
