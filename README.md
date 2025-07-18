# musl-toolchain

`musl_toolchain` provides a `cc_toolchain` implementation for Bazel.

This toolchain allows cross-compiling binaries for Linux from various platforms. It can be used to produce binaries which don't dynamically link `libc`, by statically linking `musl`'s `libc` implementation.

The supported execution platforms are:

* Linux x86_64
* Linux arm64
* macOS x86_64
* macOS arm64

The supported target platforms are: 

* Linux x86_64
* Linux arm64

The toolchain binaries are statically linked against musl on Linux and thus don't require (a particular version of) glibc to be available.

## Setup

Setup instructions are available with [each release](https://github.com/bazel-contrib/musl-toolchain/releases).

`--incompatible_enable_cc_toolchain_resolution` is required with Bazel 6.

## Usage

The toolchain automatically enables the `fully_static_link` feature to produce statically linked binaries that run anywhere.

`cc_binary` targets with dynamic library dependencies (e.g. `dynamic_deps` or `cc_import`s), `linkstatic = False` or `--dynamic_mode=fully` will be linked dynamically. Such binaries require the `musl` dynamic linker to be present at `/lib/ld-musl-<arch>.so.1` on the target system.
Since the path to the dynamic linker is hardcoded into the binary as an absolute path, there is no way to supply it hermetically.

Dynamically linked `cc_test`s are automatically executed with a hermetic `musl` dynamic linker (requires Bazel 7 or higher).

## Comparison with other `cc_toolchain` implementations

### [aspect-build/gcc-toolchain](https://github.com/aspect-build/gcc-toolchain)

gcc-toolchain supports building against a known glibc version, rather than building static binaries linking the musl libc implementation.

It also isn't set up for cross-compiling from macOS.

If you're aiming to only compile from Linux, and don't need statically linked binaries, the gcc-toolchain is worth considering.

### [grailbio/llvm-toolchain](https://github.com/grailbio/bazel-toolchain)

`llvm-toolchain` supports cross-compiling, but requires bringing along a sysroot containing a libc to link against.

In contrast, the musl toolchain is designed for building static binaries linking the musl libc implementation.

The musl toolchain's C/C++ compiler is gcc-based rather than llvm-based.

If you don't need to produce statically linked binaries, this toolchain is worth considering.

### [uber/hermetic_cc_toolchain](https://github.com/uber/hermetic_cc_toolchain)

These toolchains have similar aims.

From having tried out the Zig toolchain, the authors of this toolchain have run into stability/reliability issues due to the relatively early stage of development that Zig is currently at. We look forward to the Zig toolchain maturing beyond these issues in the future!
