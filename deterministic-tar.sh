#!/bin/bash

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo >&2 "Usage: $0 out_file.tar.gz files..."
  exit 1
fi
out_file="$1"
shift

# Use gnutar so that we can set --mtime to not set mtime for individual files in the archive.
# Use gzip separately so that we can set -n to not embed a timestamp in bytes 5-8 of the gzip'd file.
os="$(uname)"
set +e
if [[ "${os}" == "Darwin" ]]; then
  gnutar_bin="$(which gtar)"
  if [[ "${gnutar_bin}" == "" ]]; then
    echo >&2 "Couldn't find gtar - perhaps you want to \`brew install gnu-tar\`"
    exit 1
  fi
else
  gnutar_bin="$(which gnutar)"
  if [[ "${gnutar_bin}" == "" ]]; then
    tar="$(which tar)"
    echo >&2 "Couldn't find gnutar"
    if [[ "${tar}" != "" ]]; then
      echo >&2 "If your ${tar} is the GNU tar, maybe you want to \`ln -s ${tar} /usr/bin/gnutar\`"
    fi
    exit 1
  fi
fi
set -e
for f in "$@"; do
  [[ -e "${f}" ]] || { echo >&2 "${f} didn't exist in $(pwd)" ; exit 1 ;}
done
"$gnutar_bin" --owner root --group wheel --mtime='UTC 1980-01-01' -cf /dev/stdout "$@" | gzip -n > "$out_file"
