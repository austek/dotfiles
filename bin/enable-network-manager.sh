#!/usr/bin/env bash
# Reverses disable-network-manager: unmasks, enables, and starts NetworkManager.
set -euo pipefail

if ! dpkg -l network-manager 2>/dev/null | grep -q '^ii'; then
    echo "network-manager is not installed. Install it first: sudo apt install network-manager" >&2
    exit 1
fi

sudo systemctl unmask NetworkManager
sudo systemctl enable --now NetworkManager

echo "NetworkManager re-enabled and started:"
systemctl is-active NetworkManager
