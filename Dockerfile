FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Kolkata \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt .

# requirements.txt is UTF-16 in the repo; normalise to UTF-8 before pip reads it
RUN python -c "d=open('requirements.txt','rb').read(); t=d.decode('utf-16') if d[:2] in (b'\xff\xfe',b'\xfe\xff') else d.decode('utf-8-sig'); open('/tmp/req.txt','w',newline='\n').write(t.replace('\r',''))" \
 && pip install -r /tmp/req.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY . .
RUN mkdir -p data logs screenshots

EXPOSE 80
CMD ["python", "app.py"]
