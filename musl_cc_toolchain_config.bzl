load(
    "@bazel_tools//tools/build_defs/cc:action_names.bzl",
    _ASSEMBLE_ACTION_NAME = "ASSEMBLE_ACTION_NAME",
    _CLIF_MATCH_ACTION_NAME = "CLIF_MATCH_ACTION_NAME",
    _CPP_COMPILE_ACTION_NAME = "CPP_COMPILE_ACTION_NAME",
    _CPP_HEADER_PARSING_ACTION_NAME = "CPP_HEADER_PARSING_ACTION_NAME",
    _CPP_LINK_DYNAMIC_LIBRARY_ACTION_NAME = "CPP_LINK_DYNAMIC_LIBRARY_ACTION_NAME",
    _CPP_LINK_EXECUTABLE_ACTION_NAME = "CPP_LINK_EXECUTABLE_ACTION_NAME",
    _CPP_LINK_NODEPS_DYNAMIC_LIBRARY_ACTION_NAME = "CPP_LINK_NODEPS_DYNAMIC_LIBRARY_ACTION_NAME",
    _CPP_LINK_STATIC_LIBRARY_ACTION_NAME = "CPP_LINK_STATIC_LIBRARY_ACTION_NAME",
    _CPP_MODULE_CODEGEN_ACTION_NAME = "CPP_MODULE_CODEGEN_ACTION_NAME",
    _CPP_MODULE_COMPILE_ACTION_NAME = "CPP_MODULE_COMPILE_ACTION_NAME",
    _C_COMPILE_ACTION_NAME = "C_COMPILE_ACTION_NAME",
    _LINKSTAMP_COMPILE_ACTION_NAME = "LINKSTAMP_COMPILE_ACTION_NAME",
    _LTO_BACKEND_ACTION_NAME = "LTO_BACKEND_ACTION_NAME",
    _PREPROCESS_ASSEMBLE_ACTION_NAME = "PREPROCESS_ASSEMBLE_ACTION_NAME",
)
load(
    "@bazel_tools//tools/cpp:cc_toolchain_config_lib.bzl",
    "action_config",
    "feature",
    "flag_group",
    "flag_set",
    "tool",
    "tool_path",
    "with_feature_set",
)

all_link_actions = [
    _CPP_LINK_EXECUTABLE_ACTION_NAME,
    _CPP_LINK_DYNAMIC_LIBRARY_ACTION_NAME,
    _CPP_LINK_NODEPS_DYNAMIC_LIBRARY_ACTION_NAME,
]

def _impl(ctx):
    target_arch = ctx.attr.target_arch
    target_cpu = "k8" if ctx.attr.target_arch == "x86_64" else "arm64"

    objcopy_embed_data_action = action_config(
        action_name = "objcopy_embed_data",
        enabled = True,
        tools = [tool(path = "bin/" + target_arch + "-linux-musl-objcopy")],
    )

    tool_paths = [
        tool_path(name = "gcc", path = "bin/" + target_arch + "-linux-musl-gcc"),
        tool_path(name = "ld", path = "bin/" + target_arch + "-linux-musl-ld"),
        tool_path(name = "compat-ld", path = "bin/" + target_arch + "-linux-musl-ld"),
        tool_path(name = "dwp", path = "/usr/bin/false"),
        tool_path(name = "ar", path = "bin/" + target_arch + "-linux-musl-ar"),
        tool_path(name = "cpp", path = "bin/" + target_arch + "-linux-musl-cpp"),
        tool_path(name = "gcov", path = "bin/" + target_arch + "-linux-musl-gcov"),
        tool_path(name = "nm", path = "bin/" + target_arch + "-linux-musl-nm"),
        tool_path(name = "objcopy", path = "bin/" + target_arch + "-linux-musl-objcopy"),
        tool_path(name = "objdump", path = "bin/" + target_arch + "-linux-musl-objdump"),
        tool_path(name = "strip", path = "bin/" + target_arch + "-linux-musl-strip"),
    ]

    default_link_flags_feature = feature(
        name = "default_link_flags",
        enabled = True,
        flag_sets = [
            flag_set(
                actions = all_link_actions,
                flag_groups = [
                    flag_group(
                        flags = [
                            "-lstdc++",
                            "-Wl,-z,relro,-z,now",
                            "-no-canonical-prefixes",
                            "-pass-exit-codes",
                        ],
                    ),
                ],
            ),
            flag_set(
                actions = all_link_actions,
                flag_groups = [flag_group(flags = ["-Wl,--gc-sections"])],
                with_features = [with_feature_set(features = ["opt"])],
            ),
        ],
    )

    gcc_quoting_for_param_files_feature = feature(name = "gcc_quoting_for_param_files", enabled = True)

    archive_param_file_feature = feature(name = "archive_param_file", enabled = True)

    unfiltered_compile_flags_feature = feature(
        name = "unfiltered_compile_flags",
        enabled = True,
        flag_sets = [
            flag_set(
                actions = [
                    _ASSEMBLE_ACTION_NAME,
                    _PREPROCESS_ASSEMBLE_ACTION_NAME,
                    _LINKSTAMP_COMPILE_ACTION_NAME,
                    _C_COMPILE_ACTION_NAME,
                    _CPP_COMPILE_ACTION_NAME,
                    _CPP_HEADER_PARSING_ACTION_NAME,
                    _CPP_MODULE_COMPILE_ACTION_NAME,
                    _CPP_MODULE_CODEGEN_ACTION_NAME,
                    _LTO_BACKEND_ACTION_NAME,
                    _CLIF_MATCH_ACTION_NAME,
                ],
                flag_groups = [
                    flag_group(
                        flags = [
                            "-no-canonical-prefixes",
                            "-fno-canonical-system-headers",
                            "-Wno-builtin-macro-redefined",
                            "-D__DATE__=\"redacted\"",
                            "-D__TIMESTAMP__=\"redacted\"",
                            "-D__TIME__=\"redacted\"",
                        ],
                    ),
                ],
            ),
        ],
    )

    supports_pic_feature = feature(name = "supports_pic", enabled = True)

    default_compile_flags_feature = feature(
        name = "default_compile_flags",
        enabled = True,
        flag_sets = [
            flag_set(
                actions = [
                    _ASSEMBLE_ACTION_NAME,
                    _PREPROCESS_ASSEMBLE_ACTION_NAME,
                    _LINKSTAMP_COMPILE_ACTION_NAME,
                    _C_COMPILE_ACTION_NAME,
                    _CPP_COMPILE_ACTION_NAME,
                    _CPP_HEADER_PARSING_ACTION_NAME,
                    _CPP_MODULE_COMPILE_ACTION_NAME,
                    _CPP_MODULE_CODEGEN_ACTION_NAME,
                    _LTO_BACKEND_ACTION_NAME,
                    _CLIF_MATCH_ACTION_NAME,
                ],
                flag_groups = [
                    flag_group(
                        flags = [
                            "-U_FORTIFY_SOURCE",
                            "-D_FORTIFY_SOURCE=1",
                            "-fstack-protector",
                            "-Wall",
                            "-Wunused-but-set-parameter",
                            "-Wno-free-nonheap-object",
                            "-fno-omit-frame-pointer",
                        ],
                    ),
                ],
            ),
            flag_set(
                actions = [
                    _ASSEMBLE_ACTION_NAME,
                    _PREPROCESS_ASSEMBLE_ACTION_NAME,
                    _LINKSTAMP_COMPILE_ACTION_NAME,
                    _C_COMPILE_ACTION_NAME,
                    _CPP_COMPILE_ACTION_NAME,
                    _CPP_HEADER_PARSING_ACTION_NAME,
                    _CPP_MODULE_COMPILE_ACTION_NAME,
                    _CPP_MODULE_CODEGEN_ACTION_NAME,
                    _LTO_BACKEND_ACTION_NAME,
                    _CLIF_MATCH_ACTION_NAME,
                ],
                flag_groups = [flag_group(flags = ["-g"])],
                with_features = [with_feature_set(features = ["dbg"])],
            ),
            flag_set(
                actions = [
                    _ASSEMBLE_ACTION_NAME,
                    _PREPROCESS_ASSEMBLE_ACTION_NAME,
                    _LINKSTAMP_COMPILE_ACTION_NAME,
                    _C_COMPILE_ACTION_NAME,
                    _CPP_COMPILE_ACTION_NAME,
                    _CPP_HEADER_PARSING_ACTION_NAME,
                    _CPP_MODULE_COMPILE_ACTION_NAME,
                    _CPP_MODULE_CODEGEN_ACTION_NAME,
                    _LTO_BACKEND_ACTION_NAME,
                    _CLIF_MATCH_ACTION_NAME,
                ],
                flag_groups = [
                    flag_group(
                        flags = [
                            "-g0",
                            "-O2",
                            "-DNDEBUG",
                            "-ffunction-sections",
                            "-fdata-sections",
                        ],
                    ),
                ],
                with_features = [with_feature_set(features = ["opt"])],
            ),
            flag_set(
                actions = [
                    _LINKSTAMP_COMPILE_ACTION_NAME,
                    _CPP_COMPILE_ACTION_NAME,
                    _CPP_HEADER_PARSING_ACTION_NAME,
                    _CPP_MODULE_COMPILE_ACTION_NAME,
                    _CPP_MODULE_CODEGEN_ACTION_NAME,
                    _LTO_BACKEND_ACTION_NAME,
                    _CLIF_MATCH_ACTION_NAME,
                ],
                flag_groups = [flag_group(flags = ["-std=c++14"])],
            ),
        ],
    )

    random_seed_feature = feature(
        name = "random_seed",
        enabled = True,
        flag_sets = [
            flag_set(
                actions = [
                    _C_COMPILE_ACTION_NAME,
                    _CPP_COMPILE_ACTION_NAME,
                    _CPP_MODULE_CODEGEN_ACTION_NAME,
                    _CPP_MODULE_COMPILE_ACTION_NAME,
                ],
                flag_groups = [
                    flag_group(
                        flags = ["-frandom-seed=%{output_file}"],
                        expand_if_available = "output_file",
                    ),
                ],
            ),
        ],
    )

    opt_feature = feature(name = "opt")

    supports_dynamic_linker_feature = feature(name = "supports_dynamic_linker", enabled = True)

    objcopy_embed_flags_feature = feature(
        name = "objcopy_embed_flags",
        enabled = True,
        flag_sets = [
            flag_set(
                actions = ["objcopy_embed_data"],
                flag_groups = [flag_group(flags = ["-I", "binary"])],
            ),
        ],
    )

    dbg_feature = feature(name = "dbg")

    static_link_cpp_runtimes_feature = feature(
        name = "static_link_cpp_runtimes",
        enabled = True,
    )

    fully_static_link_feature = feature(
        name = "fully_static_link",
        enabled = True,
        flag_sets = [
            flag_set(
                actions = [
                    _CPP_LINK_EXECUTABLE_ACTION_NAME,
                    _CPP_LINK_DYNAMIC_LIBRARY_ACTION_NAME,
                ],
                flag_groups = [
                    flag_group(
                        flags = ["-static"],
                        # Executables with dynamic libraries in deps can't be fully static.
                        # This includes both cc_test on Linux with default --dynamic_mode as well as
                        # e.g. cc_binary with dynamic_deps. Since tests are rarely cross-compiled,
                        expand_if_false = "runtime_library_search_directories",
                    ),
                ],
            ),
        ],
    )

    user_compile_flags_feature = feature(
        name = "user_compile_flags",
        enabled = True,
        flag_sets = [
            flag_set(
                actions = [
                    _ASSEMBLE_ACTION_NAME,
                    _PREPROCESS_ASSEMBLE_ACTION_NAME,
                    _LINKSTAMP_COMPILE_ACTION_NAME,
                    _C_COMPILE_ACTION_NAME,
                    _CPP_COMPILE_ACTION_NAME,
                    _CPP_HEADER_PARSING_ACTION_NAME,
                    _CPP_MODULE_COMPILE_ACTION_NAME,
                    _CPP_MODULE_CODEGEN_ACTION_NAME,
                    _LTO_BACKEND_ACTION_NAME,
                    _CLIF_MATCH_ACTION_NAME,
                ],
                flag_groups = [
                    flag_group(
                        flags = ["%{user_compile_flags}"],
                        iterate_over = "user_compile_flags",
                        expand_if_available = "user_compile_flags",
                    ),
                ],
            ),
        ],
    )

    sysroot_feature = feature(
        name = "sysroot",
        enabled = True,
        flag_sets = [
            flag_set(
                actions = [
                    _PREPROCESS_ASSEMBLE_ACTION_NAME,
                    _LINKSTAMP_COMPILE_ACTION_NAME,
                    _C_COMPILE_ACTION_NAME,
                    _CPP_COMPILE_ACTION_NAME,
                    _CPP_HEADER_PARSING_ACTION_NAME,
                    _CPP_MODULE_COMPILE_ACTION_NAME,
                    _CPP_MODULE_CODEGEN_ACTION_NAME,
                    _LTO_BACKEND_ACTION_NAME,
                    _CLIF_MATCH_ACTION_NAME,
                    _CPP_LINK_EXECUTABLE_ACTION_NAME,
                    _CPP_LINK_DYNAMIC_LIBRARY_ACTION_NAME,
                    _CPP_LINK_STATIC_LIBRARY_ACTION_NAME,
                    _CPP_LINK_NODEPS_DYNAMIC_LIBRARY_ACTION_NAME,
                ],
                flag_groups = [
                    flag_group(
                        flags = ["--sysroot=%{sysroot}"],
                        expand_if_available = "sysroot",
                    ),
                ],
            ),
        ],
    )

    generate_linkmap_feature = feature(
        name = "generate_linkmap",
        flag_sets = [
            flag_set(
                actions = [
                    _CPP_LINK_EXECUTABLE_ACTION_NAME,
                ],
                flag_groups = [
                    flag_group(
                        flags = [
                            "-Wl,-Map=%{output_execpath}.map",
                        ],
                        expand_if_available = "output_execpath",
                    ),
                ],
            ),
        ],
    )

    # The default implementation of this feature uses the Google-internal
    # $EXEC_ORIGIN, which is not available in the open-source dynamic linker.
    runtime_library_search_directories_feature = feature(
        name = "runtime_library_search_directories",
        flag_sets = [
            flag_set(
                actions = all_link_actions,
                flag_groups = [
                    flag_group(
                        iterate_over = "runtime_library_search_directories",
                        flag_groups = [
                            flag_group(
                                flags = [
                                    "-Xlinker",
                                    "-rpath",
                                    "-Xlinker",
                                    "$ORIGIN/%{runtime_library_search_directories}",
                                ],
                            ),
                        ],
                        expand_if_available = "runtime_library_search_directories",
                    ),
                ],
            ),
        ],
    )

    coverage_feature = feature(
        name = "coverage",
        provides = ["profile"],
        flag_sets = [
            flag_set(
                actions = [
                    _PREPROCESS_ASSEMBLE_ACTION_NAME,
                    _C_COMPILE_ACTION_NAME,
                    _CPP_COMPILE_ACTION_NAME,
                    _CPP_HEADER_PARSING_ACTION_NAME,
                    _CPP_MODULE_COMPILE_ACTION_NAME,
                ],
                flag_groups = ([
                    flag_group(flags = [
                        "--coverage",
                    ]),
                ]),
            ),
            flag_set(
                actions = all_link_actions,
                flag_groups = ([
                    flag_group(flags = [
                        "--coverage",
                    ]),
                ]),
            ),
        ],
    )

    treat_warnings_as_errors_feature = feature(
        name = "treat_warnings_as_errors",
        flag_sets = [
            flag_set(
                actions = [
                    _C_COMPILE_ACTION_NAME,
                    _CPP_COMPILE_ACTION_NAME,
                ],
                flag_groups = [flag_group(flags = ["-Werror"])],
            ),
            flag_set(
                actions = all_link_actions,
                flag_groups = [flag_group(
                    flags = ["-Wl,-fatal-warnings"],
                )],
            ),
        ],
    )

    return cc_common.create_cc_toolchain_config_info(
        ctx = ctx,
        toolchain_identifier = target_cpu + "-musl-toolchain",
        host_system_name = "local",
        target_system_name = "local",
        target_cpu = target_cpu,
        target_libc = "musl",
        compiler = "gcc",
        abi_version = "local",
        abi_libc_version = "local",
        tool_paths = tool_paths,
        action_configs = [objcopy_embed_data_action],
        features = [
            random_seed_feature,
            generate_linkmap_feature,
            runtime_library_search_directories_feature,
            coverage_feature,
            default_compile_flags_feature,
            default_link_flags_feature,
            supports_dynamic_linker_feature,
            supports_pic_feature,
            objcopy_embed_flags_feature,
            opt_feature,
            dbg_feature,
            static_link_cpp_runtimes_feature,
            fully_static_link_feature,
            user_compile_flags_feature,
            sysroot_feature,
            unfiltered_compile_flags_feature,
            treat_warnings_as_errors_feature,
            archive_param_file_feature,
            gcc_quoting_for_param_files_feature,
        ],
    )

musl_cc_toolchain_config = rule(
    implementation = _impl,
    attrs = {
        "target_arch": attr.string(mandatory = True, values = ["aarch64", "x86_64"]),
    },
    provides = [CcToolchainConfigInfo],
)
