ARG UBUNTU_VERSION=26.04
FROM ubuntu:${UBUNTU_VERSION}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends sudo python3 git ca-certificates curl locales \
    && rm -rf /var/lib/apt/lists/* \
    && printf '%s\n' 'Defaults:ubuntu !authenticate' 'ubuntu ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/e2e \
    && chmod 0440 /etc/sudoers.d/e2e

# setup.sh refuses to run as root, so the install runs as the image's stock non-root user.
USER ubuntu
ENV USER=ubuntu
WORKDIR /e2e
COPY --chown=ubuntu:ubuntu run-preset.sh assert-preset.sh /e2e/

ENTRYPOINT ["/e2e/run-preset.sh"]