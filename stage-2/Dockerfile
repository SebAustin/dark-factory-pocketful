FROM python:3.12-alpine

WORKDIR /srv
# app/ and the designer's web/ (if present); tests, docs and tools are in .dockerignore.
COPY . ./

ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080
USER nobody

CMD ["python", "-m", "app.server"]
