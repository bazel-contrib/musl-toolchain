# musl-toolchain

`musl_toolchain` provides a `cc_toolchain` implementation for Bazel.

This toolchain allows cross-compiling binaries for Linux from various platforms. It can be used to produce binaries which don't dynamically link `libc`, by statically linking `musl`'s `libc` implementation.
