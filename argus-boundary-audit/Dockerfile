FROM python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81
ENV PATH="/opt/venv/bin:$PATH" \
    HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    AI_PROVIDER=none
RUN python -m venv /opt/venv && chown -R 65534:65534 /opt/venv
COPY requirements.lock /requirements.lock
USER 65534:65534
RUN python -m pip --isolated install --no-cache-dir --only-binary=:all: --no-deps --index-url=https://pypi.org/simple -r /requirements.lock && python -m pip check
WORKDIR /src
