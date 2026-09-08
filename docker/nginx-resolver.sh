#!/bin/sh
# Rewrite the nginx `resolver` directive from the container's DNS config so
# `location /api/` (docker/nginx.conf) can re-resolve the `api` service at
# runtime. Without this nginx caches the backend IP at worker start, and
# `compose up --force-recreate api` (new IP) then 502s every /api/* request
# until nginx is restarted too.
#
# Runs from /docker-entrypoint.d/ (the official nginx image sources/execs those
# before starting nginx). Engine-agnostic: it uses whatever nameserver
# /etc/resolv.conf carries - Docker's embedded DNS (127.0.0.11), Podman's
# aardvark-dns (the network gateway), a corp resolver, etc. The image ships a
# build-time default at the same path, so `include` in nginx.conf never fails
# even if this script is skipped.
set -eu

target=/etc/nginx/lexis-resolver.conf

ns=$(awk '/^nameserver/ { print $2; exit }' /etc/resolv.conf 2>/dev/null || true)
[ -n "${ns:-}" ] || ns=127.0.0.11
case $ns in
    *:*) ns="[$ns]" ;;  # bracket IPv6 literals
esac

printf 'resolver %s valid=10s ipv6=off;\n' "$ns" > "$target"
echo "lexis: nginx /api upstream resolver -> $ns" >&2
