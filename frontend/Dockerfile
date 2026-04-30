FROM nginx:alpine

# Remove default nginx website
RUN rm -rf /usr/share/nginx/html/*

# Copy your static frontend files
COPY . /usr/share/nginx/html

# Optional: custom nginx config for SPA-like routing (safe even without frameworks)
# COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
