---
description: Diagnose and prune Claude Code context.
argument-hint: "[diagnose|treat|reload|guard|doctor]"
---

# Cozempic CLI (`pip install cozempic`)
- **No args**: Run `cozempic current 2>/dev/null`. Show size summary. Ask User: 1. Diagnose, 2. Treat & Reload (Default), 3. Treat Only, 4. Guard Mode.
- **Args**: Route directly. `reload` or `treat` -> Treat & Reload.
- **Diagnose**: `cozempic current --diagnose`. Show tokens/context %. Recommend: `gentle` (<5MB), `standard` (5-20MB), `aggressive` (>20MB). Ask to treat.
- **Treat & Reload**: Diagnose -> Dry-run (`cozempic treat current -rx <rx>`) -> Show token savings -> Ask -> Execute `cozempic reload -rx <rx>`. Tell user: "/exit to open fresh terminal".
- **Treat Only** (Manual resume): Diagnose -> Dry-run -> Execute `cozempic treat current -rx <rx> --execute`. Tell user: "Run `claude --resume`".
- **Guard Mode** (Agent Teams): Always recommend for teams (prevents state loss). Run `cozempic guard --threshold 50 -rx standard --interval 30`.
- **Doctor**: `cozempic doctor [--fix]`.
- **Safety**: Dry-run first. Never touch uuid/parentUuid. Team messages protected.
