# Build the React app
FROM node:20-alpine AS app
WORKDIR /build
COPY app/package*.json ./
RUN npm ci
COPY app/ ./
RUN npm run build

# Serve it (and the classic dashboard) with the Express server
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY server.js ./
COPY public ./public
COPY --from=app /build/dist ./dist
EXPOSE 3001
CMD ["npm", "start"]
