#!/usr/bin/env bash
# Bộ cài igam3-screen (màn hình 3.5" của máy iGam3 M1). Chép file này sang máy mới rồi chạy:
#   bash igam3-screen-installer-VERSION.run            (thêm --help để xem tuỳ chọn)
set -euo pipefail
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
LINE=$(awk '/^__IGAM3_PAYLOAD__$/ { print NR + 1; exit }' "$0")
tail -n +"$LINE" "$0" | tar -xzf - -C "$TMP"
bash "$TMP/igam3-screen/install.sh" "$@"
exit
__IGAM3_PAYLOAD__
