# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0
# Single image; ROLE (customer|supplier) is chosen per service in docker-compose.
FROM python:3.13-slim

WORKDIR /app

# Dependencies first for layer caching (kept tiny: Flask + BaSyx SDK + requests).
# Pinned exact so a new upstream release can't silently break the build.
RUN pip install --no-cache-dir "flask==3.1.3" "basyx-python-sdk==2.1.0" "requests==2.34.2"

COPY . /app

ENV HOST=0.0.0.0 PORT=5000 PYTHONUNBUFFERED=1
EXPOSE 5000
CMD ["python", "run.py"]
