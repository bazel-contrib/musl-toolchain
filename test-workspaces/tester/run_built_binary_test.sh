#!/bin/bash

set -x

built_binary="$1"
want_os="$2"
want_arch="$3"

output="$("${built_binary}")"

if [[ "${output}" != "Built on ${want_os} ${want_arch}" ]]; then
    echo >&2 "Wrong output - got ${output}"
    exit 1
fi
