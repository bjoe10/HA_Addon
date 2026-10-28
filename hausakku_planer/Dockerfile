ARG BUILD_FROM
FROM ${BUILD_FROM}
RUN apk add --no-cache python3 py3-aiohttp tzdata
WORKDIR /app
COPY app/ /app/
COPY run.sh /run.sh
RUN chmod a+x /run.sh
CMD ["/run.sh"]
