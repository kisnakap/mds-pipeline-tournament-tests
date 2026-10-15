FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Runtime uses only the standard library; pytest is needed for the test suite.
COPY --chown=app:app requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app pyproject.toml README.md main.py tournament_main.py ./
COPY --chown=app:app pipeline ./pipeline
COPY --chown=app:app tournament ./tournament
COPY --chown=app:app tests ./tests

USER app

# Default: run the full test suite. Other entry points are in docker-compose.yml and README.md examples.
CMD ["python", "-m", "pytest", "-v"]
