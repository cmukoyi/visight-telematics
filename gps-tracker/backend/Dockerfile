FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY ./backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ./backend/ .

# Create static directory and copy QR asset HTML files from customer-dashboard
# These are served by the backend for QR code scans (public endpoints, no auth)
RUN mkdir -p /app/static
COPY ./customer-dashboard/public/asset.html /app/static/asset.html
COPY ./customer-dashboard/public/scanner.html /app/static/scanner.html

EXPOSE 8000

# Copy entrypoint script
COPY ./backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
