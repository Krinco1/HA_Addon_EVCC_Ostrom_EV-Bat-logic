ARG BUILD_FROM
FROM $BUILD_FROM

# CACHE BREAKER - Ändere dieses Datum um Rebuild zu erzwingen!
ENV REBUILD_FORCE="2024-02-08-17-05-v3.0.5-FINAL"
RUN echo "EVCC-Smartload v3.0.5 - Build: 2024-02-08-17-05"

# Install Python dependencies
RUN apk add --no-cache python3 py3-pip py3-requests py3-numpy py3-yaml

# Install vehicle API packages (optional - graceful degradation if unavailable)
RUN pip3 install --no-cache-dir --break-system-packages \
    aiohttp \
    hyundai_kia_connect_api \
    renault-api \
    || echo "Some vehicle API packages could not be installed"

# Copy application
COPY rootfs /

# Make scripts executable (BOTH run and finish!)
RUN chmod a+x /etc/services.d/evcc-smartload/run && \
    chmod a+x /etc/services.d/evcc-smartload/finish

WORKDIR /app
