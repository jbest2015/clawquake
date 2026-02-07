FROM nginx:alpine

# Remove default config
RUN rm /etc/nginx/conf.d/default.conf

# Copy our config and web files
COPY nginx.conf /etc/nginx/nginx.conf
COPY ../web/ /usr/share/nginx/html/

EXPOSE 80
