server {
    listen 80;
    listen [::]:80;
    server_name iroad.ly www.iroad.ly;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/iroadweb;
        try_files $uri =404;
    }

    location / {
        return 301 https://iroad.ly$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name iroad.ly www.iroad.ly;

    ssl_certificate     /etc/letsencrypt/live/iroad.ly/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/iroad.ly/privkey.pem;

    client_max_body_size 25m;

    location /static/ {
        alias /opt/irs-road/app/app/static/;
    }

    location / {
        proxy_pass http://unix:/run/irs-road/gunicorn.sock:;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;

        proxy_connect_timeout 60s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
