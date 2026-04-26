# gunicorn.conf.py — https://docs.gunicorn.org/en/stable/settings.html

import multiprocessing

# Bind to localhost only — Nginx sits in front
bind = "127.0.0.1:5000"

# (2 × CPU cores) + 1 is the standard starting point
workers = multiprocessing.cpu_count() * 2 + 1

# Each worker handles up to 1000 requests before recycling (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 100  # randomise so workers don't all restart at once

# Timeouts
timeout = 30          # kill a worker if it doesn't respond in 30 s
keepalive = 5         # keep idle connections open for 5 s

# Logging
accesslog = "-"       # stdout (systemd/Docker captures it)
errorlog  = "-"
loglevel  = "info"
