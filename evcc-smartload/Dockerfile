ARG BUILD_FROM
   FROM $BUILD_FROM
   
   # Force rebuild - v3.0.2
   ENV REBUILD_DATE=2024-02-08-v3.0.2
   
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

# Make run script executable
   RUN chmod a+x /etc/services.d/evcc-smartload/run && \
       chmod a+x /etc/services.d/evcc-smartload/finish

WORKDIR /app
