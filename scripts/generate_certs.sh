#!/bin/bash
set -e

# Directory where certs will be placed
CERTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../certs" && pwd)"
mkdir -p "$CERTS_DIR"

DOMAIN_PRIMARY="${1:-nibiaanet.nibiaa.com}"
DOMAIN_SECONDARY="${2:-nibiaaplaxx.nibiaa.com}"
SERVER_IP="${3:-34.122.43.248}"

echo "================================================="
echo " Generating Self-Signed CA & SSL Certificates"
echo " Primary Domain  : $DOMAIN_PRIMARY"
echo " Secondary Domain: $DOMAIN_SECONDARY"
echo " Server IP       : $SERVER_IP"
echo " Directory       : $CERTS_DIR"
echo "================================================="

# 1. Generate Root CA Key & Certificate
echo "[1/4] Generating Root CA Key and Certificate..."
openssl genrsa -out "$CERTS_DIR/ca.key" 4096 2>/dev/null
openssl req -x509 -new -nodes -key "$CERTS_DIR/ca.key" -sha256 -days 3650 \
  -out "$CERTS_DIR/ca.crt" \
  -subj "/C=IN/ST=Karnataka/L=Bangalore/O=Nibiaa Devices/OU=NibiaaNet CA/CN=NibiaaNet Root CA"

# 2. Generate Server Key & CSR Configuration
echo "[2/4] Generating Server Key and Signing Request..."
openssl genrsa -out "$CERTS_DIR/server.key" 2048 2>/dev/null

cat <<EOF > "$CERTS_DIR/csr.conf"
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[dn]
C = IN
ST = Karnataka
L = Bangalore
O = Nibiaa Devices
OU = NibiaaNet Server
CN = $DOMAIN_PRIMARY

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = $DOMAIN_PRIMARY
DNS.2 = $DOMAIN_SECONDARY
DNS.3 = localhost
IP.1 = $SERVER_IP
IP.2 = 127.0.0.1
EOF

openssl req -new -key "$CERTS_DIR/server.key" -out "$CERTS_DIR/server.csr" -config "$CERTS_DIR/csr.conf"

# 3. Create extension file for SAN
cat <<EOF > "$CERTS_DIR/cert.ext"
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = $DOMAIN_PRIMARY
DNS.2 = $DOMAIN_SECONDARY
DNS.3 = localhost
IP.1 = $SERVER_IP
IP.2 = 127.0.0.1
EOF

# 4. Sign Server Certificate with Root CA
echo "[3/4] Signing Server Certificate with Root CA..."
openssl x509 -req -in "$CERTS_DIR/server.csr" -CA "$CERTS_DIR/ca.crt" -CAkey "$CERTS_DIR/ca.key" \
  -CAcreateserial -out "$CERTS_DIR/server.crt" -days 825 -sha256 -extfile "$CERTS_DIR/cert.ext"

# Cleanup CSR files
rm -f "$CERTS_DIR/server.csr" "$CERTS_DIR/csr.conf" "$CERTS_DIR/cert.ext" "$CERTS_DIR/ca.srl"

echo "[4/4] Done! Generated files in $CERTS_DIR:"
ls -la "$CERTS_DIR"
echo "================================================="
echo "Root CA Certificate (for clients/browsers): certs/ca.crt"
echo "Server Certificate (mounted into Caddy)   : certs/server.crt"
echo "Server Key (mounted into Caddy)           : certs/server.key"
echo "================================================="
