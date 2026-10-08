# Devcontainer Dockerfile

# Get the base image
FROM python:3.11-bookworm

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Install system dependencies, VNC, and Chrome in one layer
RUN apt-get update && apt-get install -y \
    git \
    wget \
    gnupg \
    # VNC and X11 dependencies
    x11vnc \
    xvfb \
    fluxbox \
    # Chrome dependencies
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/googlechrome-linux-keyring.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/googlechrome-linux-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && apt-get clean \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=1000

# Global npm folder writable by the user, so Claude Code can auto-update
ARG NPM_GLOBAL=/usr/local/share/npm-global
ENV NPM_CONFIG_PREFIX=${NPM_GLOBAL}
ENV PATH=${NPM_GLOBAL}/bin:${PATH}

# Configure the non-root user
RUN groupadd --gid ${USER_GID} ${USERNAME} \
    && useradd --uid ${USER_UID} --gid ${USER_GID} -m -s /bin/bash ${USERNAME} \
    && apt-get update \
    && apt-get install -y --no-install-recommends sudo \
    && echo "${USERNAME} ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME} \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r npm \
    && usermod -aG npm ${USERNAME} \
    && mkdir -p ${NPM_GLOBAL} \
    && chown ${USERNAME}:npm ${NPM_GLOBAL} \
    && chmod g+s ${NPM_GLOBAL}