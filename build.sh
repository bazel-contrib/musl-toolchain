#!/bin/bash -x

set -euo pipefail

if [[ $# -ne 1 || ("$1" != "aarch64" && "$1" != "x86_64") ]]; then
  echo >&2 "Usage: $0 target-arch"
  echo >&2 "Where target-arch is one of {aarch64,x86_64}"
  exit 1
fi

this_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

TARGET_ARCH="$1"
TARGET="${TARGET_ARCH}-linux-musl"

MUSL_VERSION=1.2.3
if [[ "Linux" == "$(uname)" ]]; then
    PLATFORM=x86_64-unknown-linux-gnu
else
    if [[ "i386" = "$(uname -p)" ]]; then
        PLATFORM=x86_64-apple-darwin
    else
        PLATFORM=aarch64-apple-darwin
    fi
fi

working_directory="$(mktemp -d)"
trap "rm -rf ${working_directory}" EXIT
# Clone a fork which has Apple Silicon support - ideally https://github.com/richfelker/musl-cross-make/pull/129 would get merged at some point.
git clone https://github.com/illicitonion/musl-cross-make.git "${working_directory}"
cd "${working_directory}"
git checkout 212dcbb355bc1cbac40fe7fbf4db67447d2d710d

TARGET="${TARGET}" make MUSL_VER="${MUSL_VERSION}"
TARGET="${TARGET}" make MUSL_VER="${MUSL_VERSION}" install

cd output

cp "${this_dir}/musl_cc_toolchain_config.bzl" ./
sed -e "s#{{target_arch}}#${TARGET_ARCH}#g" "${this_dir}/musl-toolchain.BUILD.bazel.template" > ./BUILD.bazel

included_files=(musl_cc_toolchain_config.bzl BUILD.bazel bin include lib libexec "${TARGET}")

output_dir="${this_dir}/output"
mkdir -p "${output_dir}"
file_name="musl-${MUSL_VERSION}-platform-${PLATFORM}-target-${TARGET}.tar.gz"
output_file="${output_dir}/${file_name}"
"${this_dir}/deterministic-tar.sh" "${output_file}" "${included_files[@]}"

echo "Generated ${output_file}"
