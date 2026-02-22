ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install Python dependencies
RUN apk add --no-cache \
    py3-pip \
    py3-yaml \
    py3-scipy \
    && pip3 install --no-cache-dir --break-system-packages \
        pyyaml \
        numpy \
        requests \
        hyundai-kia-connect-api \
        renault-api \
        aiohttp

# Copy application files
COPY rootfs /

WORKDIR /app

CMD ["python3", "-u", "/app/main.py"]
