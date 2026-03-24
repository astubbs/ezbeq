# ezbeq Docker

Creates and publishes Docker images for [ezbeq](https://github.com/astubbs/ezbeq) to GitHub Packages.

* Exposes port 8080
* Expects a volume mapped to `/config` to allow user-supplied `ezbeq.yml`
* Supports `linux/amd64` and `linux/arm64`
* Installs the [minidsp-rs](https://github.com/mrene/minidsp-rs) binary automatically

> ⚠ This image has not been tested with USB connected devices.

## Quick start (Docker Compose)

```bash
cd docker
docker compose up -d
```

Defaults to `~/.ezbeq` for config and port `8080`. Override via a `.env` file (copy `.env.example`).

## Local development (build from source)

```bash
cd docker
cp .env.example .env
# edit .env if needed
bin/run-local
```

Uses the `dev` Dockerfile target — builds the React UI and installs ezbeq via Poetry from the local source tree.

## Build targets

| Target | Purpose |
|--------|---------|
| `production` | CI/published image — installs `ezbeq` from PyPI |
| `dev` | Local dev — builds from source using Poetry + Node/Yarn |

## Manual build

```bash
# From repo root:
docker build -f docker/Dockerfile --target production -t ezbeq .
docker build -f docker/Dockerfile --target dev -t ezbeq-dev .
```
