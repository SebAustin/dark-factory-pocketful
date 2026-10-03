FROM python:3.12-alpine

WORKDIR /srv
COPY app/ ./app/

ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080
USER nobody

CMD ["python", "-m", "app.server"]
