FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

ENV FLASK_ENV=development
ENV FLASK_DEBUG=1
ENV FLASK_APP=app:app

CMD ["python", "-m", "flask", "--app", "app", "run", "--host=0.0.0.0", "--port=5000", "--reload"]