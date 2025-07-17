"""
Test toolchain implementation for musl cross-compilation.
This provides the test runner functionality for musl cross-compilation.
"""

_CcTestInfo = provider(
    doc = "Toolchain implementation for @bazel_tools//tools/cpp:test_runner_toolchain_type",
    fields = {
        "get_runner": "Callback invoked by cc_test, should accept (ctx, binary_info, processed_environment, dynamic_linker) and return a list of providers",
        "linkopts": "Additional linkopts from an external source (e.g. toolchain)",
        "linkstatic": "If set, force this to be linked statically (i.e. --dynamic_mode=off)",
    },
)

_CcTestRunnerInfo = provider(
    doc = "Test runner implementation for @bazel_tools//tools/cpp:test_runner_toolchain_type",
    fields = {
        "args": "kwargs to pass to the test runner function",
        "func": "The test runner function with signature (ctx, binary_info, processed_environment, **kwargs)",
    },
)

def _musl_cc_test_runner_func(ctx, binary_info, processed_environment, dynamic_linker):
    cpp_config = ctx.fragments.cpp
    if cpp_config.dynamic_mode() == "OFF" or ctx.attr.linkstatic:
        executable = binary_info.executable
        runfiles = binary_info.runfiles
    else:
        executable = ctx.actions.declare_file(ctx.label.name + "_test_runner.sh")
        ctx.actions.write(
            output = executable,
            content = """\
#!/bin/sh
exec '{dynamic_linker}' '{binary}' "$@"
""".format(
                dynamic_linker = dynamic_linker.short_path,
                binary = binary_info.executable.short_path,
            ),
            is_executable = True,
        )
        runfiles = ctx.runfiles([
            dynamic_linker,
            binary_info.executable,
        ]).merge(binary_info.runfiles)

    return [
        DefaultInfo(
            executable = executable,
            files = binary_info.files,
            runfiles = runfiles,
        ),
        RunEnvironmentInfo(
            environment = processed_environment,
            inherited_environment = ctx.attr.env_inherit,
        ),
    ]

def _musl_cc_test_toolchain_impl(ctx):
    cc_test_runner_info = _CcTestRunnerInfo(
        args = {
            "dynamic_linker": ctx.file.dynamic_linker,
        },
        func = _musl_cc_test_runner_func,
    )
    cc_test_info = _CcTestInfo(
        get_runner = cc_test_runner_info,
        linkopts = [],
    )
    return [
        platform_common.ToolchainInfo(
            cc_test_info = cc_test_info,
        ),
    ]

musl_cc_test_toolchain = rule(
    implementation = _musl_cc_test_toolchain_impl,
    attrs = {
        "dynamic_linker": attr.label(
            allow_single_file = True,
            mandatory = True,
        ),
    },
)