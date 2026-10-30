ARG UBUNTU_VERSION=26.04
FROM ubuntu:${UBUNTU_VERSION}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git locales python3 sudo \
    && rm -rf /var/lib/apt/lists/* \
    && printf '%s\n' 'Defaults:ubuntu !authenticate' 'ubuntu ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/e2e \
    && chmod 0440 /etc/sudoers.d/e2e

# A container has no AppArmor securityfs, so a postinst that loads a profile (pgadmin4-desktop's) fails.
# The diversion keeps the stub in place when the apparmor package installs later.
RUN dpkg-divert --local --divert /usr/sbin/apparmor_parser.real --add /usr/sbin/apparmor_parser \
    && printf '#!/bin/sh\nexit 0\n' > /usr/sbin/apparmor_parser \
    && chmod 0755 /usr/sbin/apparmor_parser

WORKDIR /e2e
COPY --chmod=0755 run-preset.sh assert-preset.sh /e2e/

# dotfiles-setup refuses to run as root, so the install runs as the image's stock non-root user.
USER ubuntu
ENV USER=ubuntu

ENTRYPOINT ["/e2e/run-preset.sh"]