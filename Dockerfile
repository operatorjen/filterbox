FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn python-multipart playwright httpx python-dotenv

RUN playwright install chromium

COPY main.py .
COPY index.html .

EXPOSE 8000

COPY .env .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]