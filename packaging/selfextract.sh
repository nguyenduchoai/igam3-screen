#!/usr/bin/env bash
# igam3-screen installer (the 3.5" screen of the iGam3 M1). Copy this file to the computer and run:
#   bash igam3-screen-installer-VERSION.run            (--help lists the options)
set -euo pipefail
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
LINE=$(awk '/^__IGAM3_PAYLOAD__$/ { print NR + 1; exit }' "$0")
tail -n +"$LINE" "$0" | tar -xzf - -C "$TMP"
bash "$TMP/igam3-screen/install.sh" "$@"
exit
__IGAM3_PAYLOAD__
