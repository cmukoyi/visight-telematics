FROM nginx:alpine

# Copy nginx config
COPY nginx-admin.conf /etc/nginx/conf.d/default.conf

# Copy ALL admin portal HTML files and assets
COPY public/ /usr/share/nginx/html/

# Expose port
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
