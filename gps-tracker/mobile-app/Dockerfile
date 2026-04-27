# Flutter Web App Dockerfile
# Serves pre-built Flutter web app with nginx
# NOTE: Flutter app is built by GitHub Actions CI/CD pipeline, not here

FROM nginx:alpine

# Copy pre-built Flutter web files (built by GitHub Actions)
COPY ble_tracker_app/build/web /usr/share/nginx/html

# Create nginx configuration for Flutter web app with CORRECT caching strategy
RUN echo 'server {' > /etc/nginx/conf.d/default.conf && \
    echo '    listen 80;' >> /etc/nginx/conf.d/default.conf && \
    echo '    server_name localhost;' >> /etc/nginx/conf.d/default.conf && \
    echo '    root /usr/share/nginx/html;' >> /etc/nginx/conf.d/default.conf && \
    echo '    index index.html;' >> /etc/nginx/conf.d/default.conf && \
    echo '' >> /etc/nginx/conf.d/default.conf && \
    echo '    # HTML files: NEVER cache - always check with server (fixes "changes dont show" issue)' >> /etc/nginx/conf.d/default.conf && \
    echo '    location ~ ^/.*\.html$ {' >> /etc/nginx/conf.d/default.conf && \
    echo '        add_header Cache-Control "no-cache, no-store, must-revalidate";' >> /etc/nginx/conf.d/default.conf && \
    echo '        add_header Pragma "no-cache";' >> /etc/nginx/conf.d/default.conf && \
    echo '        add_header Expires "0";' >> /etc/nginx/conf.d/default.conf && \
    echo '    }' >> /etc/nginx/conf.d/default.conf && \
    echo '' >> /etc/nginx/conf.d/default.conf && \
    echo '    # Hashed bundle files (.js, .css with hash): Cache long-term (safe - content has hash in filename)' >> /etc/nginx/conf.d/default.conf && \
    echo '    location ~ \.(js|css)$ {' >> /etc/nginx/conf.d/default.conf && \
    echo '        add_header Cache-Control "public, immutable, max-age=31536000";' >> /etc/nginx/conf.d/default.conf && \
    echo '    }' >> /etc/nginx/conf.d/default.conf && \
    echo '' >> /etc/nginx/conf.d/default.conf && \
    echo '    # Service worker: NEVER cache' >> /etc/nginx/conf.d/default.conf && \
    echo '    location /flutter_service_worker.js {' >> /etc/nginx/conf.d/default.conf && \
    echo '        add_header Cache-Control "no-cache, no-store, must-revalidate";' >> /etc/nginx/conf.d/default.conf && \
    echo '        add_header Pragma "no-cache";' >> /etc/nginx/conf.d/default.conf && \
    echo '        add_header Expires "0";' >> /etc/nginx/conf.d/default.conf && \
    echo '    }' >> /etc/nginx/conf.d/default.conf && \
    echo '' >> /etc/nginx/conf.d/default.conf && \
    echo '    # Static assets (fonts, images): Cache with revalidation' >> /etc/nginx/conf.d/default.conf && \
    echo '    location ~ \.(woff2?|ttf|otf|eot|svg|gif|jpe?g|png|ico)$ {' >> /etc/nginx/conf.d/default.conf && \
    echo '        add_header Cache-Control "public, max-age=31536000, immutable";' >> /etc/nginx/conf.d/default.conf && \
    echo '    }' >> /etc/nginx/conf.d/default.conf && \
    echo '' >> /etc/nginx/conf.d/default.conf && \
    echo '    # SPA routing: fallback to index.html but dont cache it' >> /etc/nginx/conf.d/default.conf && \
    echo '    location / {' >> /etc/nginx/conf.d/default.conf && \
    echo '        try_files $uri $uri/ /index.html;' >> /etc/nginx/conf.d/default.conf && \
    echo '        add_header Cache-Control "no-cache, no-store, must-revalidate";' >> /etc/nginx/conf.d/default.conf && \
    echo '    }' >> /etc/nginx/conf.d/default.conf && \
    echo '' >> /etc/nginx/conf.d/default.conf && \
    echo '    # GZIP compression' >> /etc/nginx/conf.d/default.conf && \
    echo '    gzip on;' >> /etc/nginx/conf.d/default.conf && \
    echo '    gzip_vary on;' >> /etc/nginx/conf.d/default.conf && \
    echo '    gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript;' >> /etc/nginx/conf.d/default.conf && \
    echo '}' >> /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
