FROM python:3.12-slim

WORKDIR /app

COPY index.html server.py ./
COPY favicon.ico ./
COPY data ./data

EXPOSE 8000

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8000"]
