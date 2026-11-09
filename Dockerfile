# Capa 1: Imagen base
FROM python:3.12-slim

# Capa 2: Directorio de trabajo
WORKDIR /src

LABEL org.opencontainers.image.title="ms-dpia-agents"
ENV HOST=0.0.0.0 PORT=8302 FLASK_ENV=production
EXPOSE 8302

# Capa 3: Requisitos Python
COPY src/requirements.txt .

# Capa 4: Dependencias del sistema (bookworm-friendly)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    wget \
    curl \
    unzip \
    fonts-liberation \
    libayatana-appindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libgdk-pixbuf-2.0-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    chromium \
    chromium-driver \
 && rm -rf /var/lib/apt/lists/*

# (Opcional) Rutas útiles para Selenium/Playwright
ENV CHROME_BIN=/usr/bin/chromium \
    CHROMIUM_PATH=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Capa 5: Dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# Capa 6: Código fuente
COPY src/ .


# Capa 7: Comando por defecto
CMD ["python", "./app.py"]
