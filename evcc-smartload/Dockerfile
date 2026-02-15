ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python dependencies
RUN apk add --no-cache python3 py3-pip py3-requests py3-numpy py3-yaml

# Install vehicle API packages (optional – graceful degradation)
RUN pip3 install --no-cache-dir --break-system-packages \
    aiohttp \
    hyundai_kia_connect_api \
    renault-api \
    || echo "Some vehicle API packages could not be installed"

# Copy application rootfs
COPY rootfs /

# Copy config.yaml to where the app can find it
COPY config.yaml /app/config.yaml

# Make scripts executable
RUN chmod a+x /etc/services.d/evcc-smartload/run && \
    chmod a+x /etc/services.d/evcc-smartload/finish

WORKDIR /app
