FROM python:3.14-slim

WORKDIR /app
COPY requirements.txt requirements-integrations.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-integrations.txt
COPY . .

ENV PYTHONUNBUFFERED=1
ENV EQUILIBRIUM_HOST=0.0.0.0
ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
