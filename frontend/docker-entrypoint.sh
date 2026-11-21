#!/bin/sh
set -e

echo "[NibiaaNet Frontend] Building production bundle..."
npm run build

echo "[NibiaaNet Frontend] Starting production static preview server on port 8080..."
exec npx vite preview --host 0.0.0.0 --port 8080
