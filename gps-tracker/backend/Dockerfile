# ============ Build Stage: Compile Python packages ============
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies (gcc needed to compile packages like psycopg2)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python requirements
COPY ./backend/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ============ Runtime Stage: Slim final image ============
FROM python:3.11-slim

WORKDIR /app

# Install ONLY runtime dependencies (postgresql-client for migrations, no gcc!)
RUN apt-get update && apt-get install -y \
    postgresql-client \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled Python packages from builder stage (no gcc in final image)
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY ./backend/ .

# The i18n synchronizer scans the customer dashboard to keep database keys in
# sync with the UI served by the separate customer container.
COPY ./customer-dashboard/public/index.html /app/customer-dashboard/public/index.html
# The React app's source, so the translation sync can find its t('app.…', '…') texts
COPY ./customer-dashboard/app/src /app/customer-dashboard/app/src

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

EXPOSE 8000

# Copy entrypoint script
COPY ./backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
