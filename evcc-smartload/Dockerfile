ARG BUILD_FROM
FROM $BUILD_FROM

# AGGRESSIVE CACHE BREAKER - changes every build
ENV REBUILD_TIMESTAMP="1707409200"
RUN apk add --no-cache --virtual .cache-break curl && \
    echo "=== EVCC-Smartload v3.0.6 Build ===" && \
    echo "Timestamp: $(date +%s)" && \
    echo "Random: $RANDOM$RANDOM" && \
    apk del .cache-break

# Install Python dependencies
RUN apk add --no-cache python3 py3-pip py3-requests py3-numpy py3-yaml

# Install vehicle API packages (optional - graceful degradation if unavailable)
RUN pip3 install --no-cache-dir --break-system-packages \
    aiohttp \
    hyundai_kia_connect_api \
    renault-api \
    || echo "Some vehicle API packages could not be installed"

# Copy application rootfs
COPY rootfs /

# CRITICAL: Copy config.yaml to where main.py can find it
COPY config.yaml /app/config.yaml

# Also copy to backup location
RUN mkdir -p /etc/evcc-smartload && \
    cp /app/config.yaml /etc/evcc-smartload/config.yaml && \
    echo "Config copied to /app and /etc/evcc-smartload"

# Make scripts executable (BOTH run and finish!)
RUN chmod a+x /etc/services.d/evcc-smartload/run && \
    chmod a+x /etc/services.d/evcc-smartload/finish && \
    echo "Scripts made executable"

# FINAL CACHE BREAKER - invalidates layer every build
RUN echo "Final cache break: $(date +%s)-$RANDOM" > /tmp/cache-marker.txt && \
    cat /tmp/cache-marker.txt && \
    ls -la /app/config.yaml && \
    rm /tmp/cache-marker.txt

WORKDIR /app
