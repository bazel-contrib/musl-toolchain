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

MUSL_VERSION=1.2.5
if [[ "Linux" == "$(uname)" ]]; then
    if [[ "x86_64" == "$(uname -p)" ]]; then
        PLATFORM=x86_64-unknown-linux-gnu
        HOST=x86_64-linux-musl
    else
        PLATFORM=aarch64-unknown-linux-gnu
        HOST=aarch64-linux-musl
    fi

    working_directory="$(mktemp -d)"
    trap "rm -rf ${working_directory}" EXIT
else
    if [[ "i386" = "$(uname -p)" ]]; then
        PLATFORM=x86_64-apple-darwin
    else
        PLATFORM=aarch64-apple-darwin
    fi

    # We create a case-sensitive volume because there are files in musl which differ only in case.
    # If we built in a case-insensitive filesystem, we'd pick one of these files to include in the tar, rather than including both versions.
    volume_bundle_tempdir="$(mktemp -d /tmp/musl-build-volume-bundleXXX)"
    hdiutil create -type SPARSE -fs "Case-sensitive APFS" -size 10g -volname CS "${volume_bundle_tempdir}/volume"
    volume_bundle="${volume_bundle_tempdir}/volume.sparseimage"
    volume_mount_dir="/Volumes/musl-build-dir-$(uuidgen)"
    hdiutil attach -nobrowse -mountpoint "${volume_mount_dir}" "${volume_bundle}"
    working_directory="${volume_mount_dir}"
    # Sleep to give a little time for lingering processes using the mount dir to terminate.
    trap "cd ${this_dir} ; sleep 15 ; hdiutil detach ${volume_mount_dir} ; rm -rf ${volume_bundle_tempdir}" EXIT

fi

# This fork contains several patches:
#  * Apple Silicon support - this was taken from https://github.com/richfelker/musl-cross-make/pull/129
#  * Statically link libintl and don't dynamically link libzstd - these avoid adding runtime dependencies to the musl toolchain which may not be present where people want to use the toolchain.
#  * Fixes to support building with modern libc++ distributions, taken from https://gcc.gnu.org/bugzilla/show_bug.cgi?id=111632
#  * Strip temporary paths out of debug symbols for reproducibility
git clone https://github.com/bazel-contrib/musl-cross-make.git "${working_directory}"
cd "${working_directory}"
git checkout 58e60ab120b4588e4094263709c3f0c3ef5b0a43

# Be more resilient to https://git.savannah.gnu.org returning 50X errors.
cat <<EOF >> config.mak
DL_CMD = wget --retry-connrefused --retry-on-http-error=502,503,504 --waitretry=10 --tries=10 -c -O
EOF

# Linux uses a two-stage build in which the first stage builds a musl toolchain for the host using the host's compiler.
# The second (and on macOS only) stage then builds the final toolchain using the stage1 toolchain. This is necessary to
# avoid a glibc dependency of the final toolchain on Linux, as the host compiler is usually glibc-based.
if [[ "Linux" == "$(uname)" ]]; then
  echo "Building stage1 toolchain..."
  TARGET="${HOST}" make MUSL_VER="${MUSL_VERSION}" GNU_SITE="https://mirror.netcologne.de/gnu/"
  TARGET="${HOST}" make MUSL_VER="${MUSL_VERSION}" GNU_SITE="https://mirror.netcologne.de/gnu/" install OUTPUT="${working_directory}/output_stage1"

  echo "Building stage2 toolchain..."
  # Clean previous build artifacts but keep downloaded sources and stage1 output
  make clean
  rm -rf build/
  # See https://github.com/richfelker/musl-cross-make/issues/64#issuecomment-497881830 for why --static is needed.
  cat <<EOF >> config.mak
COMMON_CONFIG += CC="${working_directory}/output_stage1/bin/${HOST}-gcc -static --static" CXX="${working_directory}/output_stage1/bin/${HOST}-g++ -static --static"
EOF
fi

TARGET="${TARGET}" make MUSL_VER="${MUSL_VERSION}" GNU_SITE="https://mirror.netcologne.de/gnu/"
TARGET="${TARGET}" make MUSL_VER="${MUSL_VERSION}" GNU_SITE="https://mirror.netcologne.de/gnu/" install

cd output

if [[ "Linux" == "$(uname)" ]]; then
  # The Linux binaries are very large if not stripped.
  find bin libexec -type f -executable -exec strip {} \;
  # Check that gcc and g++ are stripped and statically linked.
  for bin in bin/${TARGET}-gcc bin/${TARGET}-g++ ; do
    if [[ ! -x "${bin}" ]]; then
      echo >&2 "Error: ${bin} is not executable"
      exit 1
    fi
    if ! file "${bin}" | grep -q "statically linked"; then
      echo >&2 "Error: ${bin} is not statically linked"
      exit 1
    fi
    if ! file "${bin}" | grep -q "stripped"; then
      echo >&2 "Error: ${bin} is not stripped"
      exit 1
    fi
  done
fi

# Fix up the link to the dynamic linker to be a relative path.
ln -sf libc.so "${TARGET}/lib/ld-musl-${TARGET_ARCH}.so.1"

output_name_without_extension="musl-${MUSL_VERSION}-platform-${PLATFORM}-target-${TARGET}"

cp "${this_dir}/musl_cc_toolchain_config.bzl" ./
sed -e "s#{{target_arch}}#${TARGET_ARCH}#g" -e "s#{{toolchain_name}}#${output_name_without_extension//./_}#g" "${this_dir}/musl-toolchain.BUILD.bazel.template" > ./BUILD.bazel

included_files=(musl_cc_toolchain_config.bzl BUILD.bazel bin include lib libexec "${TARGET}")

output_dir="${this_dir}/output"
mkdir -p "${output_dir}"
file_name="${output_name_without_extension}.tar.gz"
output_file="${output_dir}/${file_name}"
"${this_dir}/deterministic-tar.sh" "${output_file}" "${included_files[@]}"

echo "Generated ${output_file}"
