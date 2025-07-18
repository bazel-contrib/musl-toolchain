import os
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

import yaml

checkout = {
    "name": "Checkout repo",
    "uses": "actions/checkout@v4",
}

check_generated_files = {
    "name": "Check generated files are up to date",
    "run": "python3 generate-actions.py && git diff --exit-code",
}

platforms_version = "0.0.9"

class Architecture(Enum):
    ARM64 = 1
    X86_64 = 2

    @property
    def for_musl(self):
        match self:
            case Architecture.ARM64:
                return "aarch64"
            case Architecture.X86_64:
                return "x86_64"

    @property
    def for_bazel_platform(self):
        match self:
            case Architecture.ARM64:
                return "arm64"
            case Architecture.X86_64:
                return "x86_64"

    @property
    def for_bazel_download(self):
        match self:
            case Architecture.X86_64:
                return "amd64"
            case Architecture.ARM64:
                return "arm64"
            case _:
                raise ValueError(f"Didn't know bazel download arch for {self}")


class OS(Enum):
    Linux = 1
    MacOS = 2

    @property
    def for_musl(self):
        match self:
            case OS.Linux:
                return "unknown-linux-gnu"
            case OS.MacOS:
                return "apple-darwin"

    @property
    def for_bazel_platform(self):
        match self:
            case OS.Linux:
                return "linux"
            case OS.MacOS:
                return "osx"

    @property
    def for_bazel_download(self):
        match self:
            case OS.Linux:
                return "linux"
            case OS.MacOS:
                return "darwin"


@dataclass
class BaseRunner:
    top_level_properties: Dict[str, Any]
    build_setup_steps: List[Dict[str, Any]]
    test_setup_steps: List[Dict[str, Any]]


def install_bazel(os: OS, arch: Architecture):
    match os:
        case OS.Linux:
            return {
                "name": "Skipping downloading bazelisk - already installed",
                "run": "bazel --version",
            }
        case OS.MacOS:
            return {
                "name": "Skipping downloading bazelisk - already installed",
                "run": "bazel --version",
            }


linux_x86_64_runner = BaseRunner(
    top_level_properties={
        "runs-on": "ubuntu-24.04",
    },
    build_setup_steps=[
        {
            "name": "Install musl",
            "run": "sudo apt-get update && sudo apt-get install -y musl-dev musl-tools",
        },
        {
            "run": "sudo ln -s /usr/bin/tar /usr/bin/gnutar",
        },
    ],
    test_setup_steps=[],
)

linux_aarch64_runner = BaseRunner(
    top_level_properties={
        "runs-on": "ubuntu-24.04-arm",
    },
    build_setup_steps=[
        {
            "name": "Install musl",
            "run": "sudo apt-get update && sudo apt-get install -y musl-dev musl-tools",
        },
        {
            "run": "sudo ln -s /usr/bin/tar /usr/bin/gnutar",
        },
    ],
    test_setup_steps=[],
)

_setup_darwin_steps = [
    {
        "run": "brew install wget md5sha1sum gnu-tar",
    },
]

darwin_x86_64_runner = BaseRunner(
    top_level_properties={
        "runs-on": "macos-13",
    },
    build_setup_steps=_setup_darwin_steps,
    test_setup_steps=[],
)

darwin_aarch64_runner = BaseRunner(
    top_level_properties={
        "runs-on": "macos-15",
    },
    build_setup_steps=_setup_darwin_steps,
    test_setup_steps=[],
)


def upload(name, path):
    return {
        "name": f"Upload {name}",
        "uses": "actions/upload-artifact@v4",
        "with": {
            "name": name,
            "path": path,
            "if-no-files-found": "error",
        },
    }


def download(name):
    return {
        "name": f"Download {name}",
        "uses": "actions/download-artifact@v4",
        "with": {
            "name": name,
            "path": ".",
        },
    }

def get_platform_sha256sum(os: OS):
    match os:
        case OS.Linux:
            return "sha256sum"
        case OS.MacOS:
            return "shasum -a 256"


def musl_filename_without_extension(source_os: OS, source_arch: Architecture, target_arch: Architecture) -> str:
    return f"musl-1.2.3-platform-{source_arch.for_musl}-{source_os.for_musl}-target-{target_arch.for_musl}-linux-musl"


def musl_toolchain_target_name(source_os: OS, source_arch: Architecture, target_arch: Architecture) -> str:
    return musl_filename_without_extension(source_os, source_arch, target_arch).replace(".", "_")


def generate_builder_workspace_config_build_file(
    source_os: OS, source_arch: Architecture, target_arch: Architecture
):
    toolchain_name = musl_toolchain_target_name(source_os, source_arch, target_arch).replace(".", "_")
    content = generate_toolchain(toolchain_name, source_arch, source_os, target_arch, wrap_in_triple_quotes=False)
    content += generate_test_toolchain(toolchain_name, target_arch, wrap_in_triple_quotes=False)
    content += f"""
platform(
    name = "platform",
    constraint_values = [
        "@platforms//cpu:{target_arch.for_bazel_platform}",
        "@platforms//os:linux",
    ],
)
"""
    return {
        "name": "Generate builder workspace config BUILD.bazel file",
        "run": f"""mkdir -p test-workspaces/builder/config && cat >test-workspaces/builder/config/BUILD.bazel <<EOF
{content}
EOF
""",
    }


def generate_builder_workspace_file(source_os: OS, source_arch: Architecture, target_arch: Architecture) -> str:
    musl_filename = musl_filename_without_extension(source_os, source_arch, target_arch) + ".tar.gz"
    repository_name = musl_toolchain_target_name(source_os, source_arch, target_arch)
    content = f"""load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

http_archive(
    name = "{repository_name}",
    sha256 = "$({get_platform_sha256sum(source_os)} {musl_filename} | awk '{{print $1}}')",
    url = "file://$(pwd)/{musl_filename}",
)
"""
    return {
        "name": "Generate builder workspace file",
        "run": f"""cat >test-workspaces/builder/WORKSPACE.bazel <<EOF
{content}
EOF
""",
    }


def generate_tester_workspace_file(test_jobs):
    content = """load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_file")\n"""
    for (source_os, source_arch), job_info in test_jobs.items():
        file_path = job_info["output"]
        content += f"""
http_file(
    name = "built_binary_{source_arch.for_musl}-{source_os.for_musl}",
    executable = True,
    sha256 = "$(sha256sum {file_path} | awk '{{print $1}}')",
    url = "file://$(pwd)/{file_path}",
)
"""
    return {
        "name": "Generate tester workspace file",
        "run": f"""cat >test-workspaces/tester/WORKSPACE.bazel <<EOF
{content}
EOF
""",
    }


@dataclass
class ReleasableArtifact:
    build_job_name: str
    source_os: OS
    source_arch: Architecture
    target_os: OS
    target_arch: Architecture
    musl_filename: str

    @property
    def repo_name(self):
        return self.musl_filename.removesuffix(".tar.gz").replace(".", "_")


def download_url_for(filename, version):
    return f"https://github.com/bazel-contrib/musl-toolchain/releases/download/{version}/{filename}"


def generate_toolchain(
    repo_name, source_arch: Architecture, source_os: OS, target_arch: Architecture, wrap_in_triple_quotes: bool, extra_exec_compatible_expr: str = "", extra_target_compatible_expr: str = "", target_settings_expr: str = ""
):
    if not wrap_in_triple_quotes and (extra_exec_compatible_expr or extra_target_compatible_expr or target_settings_expr):
        raise RuntimeError("Can't set extra_{exec,target}_compatible_expr or target_settings_expr if not wrap_in_triple_quotes")

    to_return = ""
    if wrap_in_triple_quotes:
        to_return += '"""'
    to_return += f"""toolchain(
    name = "{repo_name}",
    exec_compatible_with = [
        "@platforms//cpu:{source_arch.for_bazel_platform}",
        "@platforms//os:{source_os.for_bazel_platform}",
    ]"""

    if extra_exec_compatible_expr:
        to_return += ' + """ + repr(' + extra_exec_compatible_expr + ') + """'

    to_return += f""",
    target_compatible_with = [
        "@platforms//cpu:{target_arch.for_bazel_platform}",
        "@platforms//os:linux",
    ]"""

    if extra_target_compatible_expr:
        to_return += ' + """ + repr(' + extra_target_compatible_expr + ') + """'

    if target_settings_expr:
        to_return += f""",
    target_settings = """
        to_return += '""" + repr(' + target_settings_expr + ') + """'

    to_return += f""",
    toolchain = "@{repo_name}",
    toolchain_type = "@bazel_tools//tools/cpp:toolchain_type",
)
"""

    if wrap_in_triple_quotes:
        to_return += '"""'

    return to_return


def generate_test_toolchain(
    repo_name, target_arch: Architecture, wrap_in_triple_quotes: bool, extra_target_compatible_expr: str = "", target_settings_expr: str = ""
):
    if not wrap_in_triple_quotes and (extra_target_compatible_expr or target_settings_expr):
        raise RuntimeError("Can't set extra_target_compatible_expr or target_settings_expr if not wrap_in_triple_quotes")

    to_return = ""
    if wrap_in_triple_quotes:
        to_return += '"""'
    to_return += f"""toolchain(
    name = "{repo_name}_test_toolchain",
    exec_compatible_with = [
        "@platforms//cpu:{target_arch.for_bazel_platform}",
        "@platforms//os:linux",
    ]"""

    # extra_target_compatible_with is explicitly omitted from exec_compatible_with as the test can
    # run on any CPU/OS-compatible exec platform, it does not need musl to be present.

    to_return += f""",
    target_compatible_with = [
        "@platforms//cpu:{target_arch.for_bazel_platform}",
        "@platforms//os:linux",
    ]"""

    if extra_target_compatible_expr:
        to_return += ' + """ + repr(' + extra_target_compatible_expr + ') + """'

    if target_settings_expr:
        to_return += f""",
    target_settings = """
        to_return += '""" + repr(' + target_settings_expr + ') + """'

    to_return += f""",
    toolchain = "@{repo_name}//:{repo_name}_test_toolchain",
    toolchain_type = "@bazel_tools//tools/cpp:test_runner_toolchain_type",
)
"""

    if wrap_in_triple_quotes:
        to_return += '"""'

    return to_return


def http_archive(name, sha256, url):
    return f"""http_archive(
    name = "{name}",
    sha256 = "{sha256}",
    url = "{url}",
)
"""


def generate_release_archive(toolchain_infos, output_path, version):
    toolchain_build_contents = " + ".join(
        [
            generate_toolchain(
                artifact.repo_name,
                artifact.source_arch,
                artifact.source_os,
                artifact.target_arch,
                wrap_in_triple_quotes=True,
                extra_exec_compatible_expr="rctx.attr.extra_exec_compatible_with",
                extra_target_compatible_expr="rctx.attr.extra_target_compatible_with",
                target_settings_expr="rctx.attr.target_settings",
            )
            for artifact in toolchain_infos
        ] + [
            generate_test_toolchain(
                artifact.repo_name,
                artifact.target_arch,
                wrap_in_triple_quotes=True,
                # Explicitly omit extra_exec_compatible_with as the test
                # binaries have no exec platform requirements beyond matching
                # OS/CPU.
                extra_target_compatible_expr="rctx.attr.extra_target_compatible_with",
                target_settings_expr="rctx.attr.target_settings",
            )
            for artifact in toolchain_infos
        ]
    )

    http_archives = "\n".join(
        [
            http_archive(
                name=artifact.repo_name,
                sha256=f"$(sha256sum {artifact.musl_filename} | awk '{{print $1}}')",
                url=download_url_for(artifact.musl_filename, version),
            )
            for artifact in toolchain_infos
        ]
    )
    return [
        {
            "name": "Generate MODULE.bazel",
            "run": f"""touch MODULE.bazel

version="{version}"

cat >MODULE.bazel <<EOF
module(
    name = "toolchains_musl",
    version = "${{version#v}}",
)

bazel_dep(name = "bazel_features", version = "1.9.0")
bazel_dep(name = "platforms", version = "{platforms_version}")

toolchains_musl = use_extension("//:toolchains_musl.bzl", "toolchains_musl")
use_repo(toolchains_musl, "musl_toolchains_hub")

register_toolchains("@musl_toolchains_hub//:all")
EOF
""",
        },
        {
            "name": "Generate WORKSPACE",
            "run": f"""touch WORKSPACE
""",
        },
        {
            "name": "Generate extensions.bzl",
            "run": """touch toolchains_musl.bzl

cat >toolchains_musl.bzl <<'EOF'
load("@bazel_features//:features.bzl", "bazel_features")
load(":repositories.bzl", "load_musl_toolchains")

def _toolchains_musl(module_ctx):
    extra_exec_compatible_with = []
    extra_target_compatible_with = []
    target_settings = []
    for module in module_ctx.modules:
        if not module.tags.config:
            continue
        if not module.is_root:
            fail("musl_toolchains.config can only be used from the root module. Add 'dev_dependency = True' to 'use_extension' to ignore it in non-root modules.")
        if len(module.tags.config) > 1:
            fail(
                "Only one musl_toolchains.config tag is allowed, got",
                module.tags.config[0],
                "and",
                module.tags.config[1],
            )
        config = module.tags.config[0]
        extra_exec_compatible_with = config.extra_exec_compatible_with
        extra_target_compatible_with = config.extra_target_compatible_with
        target_settings = config.target_settings

    load_musl_toolchains(
        extra_exec_compatible_with = [str(label) for label in extra_exec_compatible_with],
        extra_target_compatible_with = [str(label) for label in extra_target_compatible_with],
        target_settings = [str(label) for label in target_settings],
    )

    if bazel_features.external_deps.extension_metadata_has_reproducible:
        return module_ctx.extension_metadata(reproducible = True)
    else:
        return None

_config = tag_class(
    attrs = {
        "extra_exec_compatible_with": attr.label_list(),
        "extra_target_compatible_with": attr.label_list(),
        "target_settings": attr.label_list(),
    },
)

toolchains_musl = module_extension(
    implementation = _toolchains_musl,
    tag_classes = {
        "config": _config,
    },
)
EOF
""",
        },
        {
            "name": "Generate BUILD.bazel",
            "run": """touch BUILD.bazel""",
        },
        {
            "name": "Generate toolchains.bzl",
            "run": f"""cat >toolchains.bzl <<EOF
def register_musl_toolchains():
    native.register_toolchains("@musl_toolchains_hub//:all")
EOF
""",
        },
        {
            "name": "Generate repositories.bzl",
            "run": f"""cat >repositories.bzl <<EOF
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

def _toolchain_repo(rctx):
    rctx.file(
        "BUILD.bazel",
        {toolchain_build_contents},
    )

toolchain_repo = repository_rule(
    implementation = _toolchain_repo,
    attrs = {{
        "extra_exec_compatible_with": attr.string_list(),
        "extra_target_compatible_with": attr.string_list(),
        "target_settings": attr.string_list(),
    }},
)

def load_musl_toolchains(extra_exec_compatible_with=[], extra_target_compatible_with=[], target_settings=[]):
{textwrap.indent(http_archives, "    ")}

    toolchain_repo(
        name = "musl_toolchains_hub",
        extra_exec_compatible_with = extra_exec_compatible_with,
        extra_target_compatible_with = extra_target_compatible_with,
        target_settings = target_settings,
    )
EOF
""",
        },
        {
            "name": "Generate bcr_test/.bazelrc",
            "run": '''mkdir -p bcr_test

cat >bcr_test/.bazelrc <<'EOF'
common --//:toolchain_flavor=musl
common --repo_env=BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1

# Simulate extra execution platforms that could run the transitioned cc_test
# binaries to verify that the test toolchain works correctly.
common --extra_execution_platforms=@platforms//host,//:linux_x86_64,//:linux_aarch64

common --test_output=errors
common --verbose_failures
EOF
'''
        },
        {
            "name": "Generate bcr_test/MODULE.bazel",
            "run": f"""mkdir -p bcr_test
touch bcr_test/MODULE.bazel

cat >bcr_test/MODULE.bazel <<'EOF'
bazel_dep(name = "toolchains_musl")
local_path_override(
    module_name = "toolchains_musl",
    path = "..",
)

bazel_dep(name = "aspect_bazel_lib", version = "2.20.0")
bazel_dep(name = "bazel_skylib", version = "1.7.1")
bazel_dep(name = "platforms", version = "{platforms_version}")
bazel_dep(name = "rules_cc", version = "0.1.3")
bazel_dep(name = "rules_shell", version = "0.5.0")

toolchains_musl = use_extension("@toolchains_musl//:toolchains_musl.bzl", "toolchains_musl", dev_dependency = True)
toolchains_musl.config(
    extra_target_compatible_with = ["//:musl_on"],
    target_settings = ["//:musl_flavor"],
)

EOF
""",
        },
        {
            "name": "Generate bcr_test/BUILD.bazel",
            "run": '''mkdir -p bcr_test
touch bcr_test/BUILD.bazel

cat >bcr_test/BUILD.bazel <<'EOF2'
load("@aspect_bazel_lib//lib:transitions.bzl", "platform_transition_binary")
load("@bazel_skylib//rules:common_settings.bzl", "string_flag")
load("@platforms//host:constraints.bzl", "HOST_CONSTRAINTS")
load("@rules_cc//cc:cc_binary.bzl", "cc_binary")
load("@rules_cc//cc:cc_library.bzl", "cc_library")
load("@rules_cc//cc:cc_shared_library.bzl", "cc_shared_library")
load("@rules_cc//cc:cc_test.bzl", "cc_test")
load("@rules_shell//shell:sh_test.bzl", "sh_test")

package(default_visibility = ["//visibility:public"])

genrule(
    name = "generate_lib_header",
    outs = ["lib.h"],
    cmd = """cat >$@ <<'EOF'
#ifndef LIB_H
#define LIB_H

const char* get_build_info();

#endif // LIB_H
EOF
""",
)

genrule(
    name = "generate_lib_source",
    outs = ["lib.cc"],
    cmd = """cat >$@ <<EOF
#include "lib.h"

#include <cstdio>

static const char* os = "$$(uname)";
static const char* arch = "$$(uname -m)";

const char* get_build_info() {
  static char info[256];
  snprintf(info, sizeof(info), "Built for %s on %s", os, arch);
  return info;
}
EOF
""",
)

cc_library(
    name = "lib",
    srcs = ["lib.cc"],
    hdrs = ["lib.h"],
    tags = ["manual"],
)

genrule(
    name = "generate_main_source",
    outs = ["main.cc"],
    cmd = """cat >$@ <<'EOF'
#include <stdio.h>
#include "lib.h"

int main(void) {
  printf("%s\\\\n", get_build_info());
  return 0;
}
EOF
""",
)

cc_binary(
    name = "binary",
    srcs = ["main.cc"],
    tags = ["manual"],
    deps = [":lib"],
)

cc_test(
    name = "test",
    srcs = ["main.cc"],
    tags = ["manual"],
    deps = [":lib"],
)

cc_shared_library(
    name = "shared_lib",
    tags = ["manual"],
    deps = [":lib"],
)

cc_binary(
    name = "shared_binary",
    srcs = ["main.cc"],
    dynamic_deps = [":shared_lib"],
    tags = ["manual"],
    deps = [":lib"],
)

[
    platform_transition_binary(
        name = "{}_{}".format(name, target_platform),
        testonly = True,
        binary = ":{}".format(name),
        target_platform = ":{}".format(target_platform),
    )
    for name in [
        "binary",
        "shared_binary",
        "test",
    ]
    for target_platform in [
        "linux_x86_64",
        "linux_aarch64",
    ]
]

HOST_PLATFORM = "{}_{}".format(
    "linux" if "@platforms//os:linux" in HOST_CONSTRAINTS else "darwin",
    "x86_64" if "@platforms//cpu:x86_64" in HOST_CONSTRAINTS else "aarch64",
)

[
    sh_test(
        name = "{}_{}_test".format(name, target_platform),
        srcs = ["binary_test.sh"],
        args = [
            {
                "binary": "'statically linked'",
                "shared_binary": "'dynamically linked'",
                "test": "'POSIX shell script'",
            }.get(name),
        ] + [
            "x86-64" if target_platform == "linux_x86_64" else "aarch64",
        ] if name != "test" else [],
        data = [":{}_{}".format(name, target_platform)],
        env = {
            "BINARY": "$(rootpath :{}_{})".format(name, target_platform),
            # Don't attempt to run shared_binary as it does require the musl linker to be installed
            # on the host system.
            "SHOULD_RUN": "1" if name != "shared_binary" and target_platform == HOST_PLATFORM else "",
        },
    )
    for name in [
        "binary",
        "shared_binary",
        "test",
    ]
    for target_platform in [
        "linux_x86_64",
        "linux_aarch64",
    ]
]

platform(
    name = "linux_x86_64",
    constraint_values = [
        "@platforms//cpu:x86_64",
        "@platforms//os:linux",
        ":musl_on",
    ],
)

platform(
    name = "linux_aarch64",
    constraint_values = [
        "@platforms//cpu:aarch64",
        "@platforms//os:linux",
        ":musl_on",
    ],
)

constraint_setting(
    name = "musl",
    default_constraint_value = ":musl_off",
)

constraint_value(
    name = "musl_on",
    constraint_setting = ":musl",
)

constraint_value(
    name = "musl_off",
    constraint_setting = ":musl",
)

string_flag(
    name = "toolchain_flavor",
    build_setting_default = "not_musl",
)

config_setting(
    name = "musl_flavor",
    flag_values = {
        ":toolchain_flavor": "musl",
    },
)
EOF2
''',
        },
        {
            "name": "Generate bcr_test/binary_test.sh",
            "run": """mkdir -p bcr_test
touch bcr_test/binary_test.sh
chmod +x bcr_test/binary_test.sh

cat >bcr_test/binary_test.sh <<'EOF'
#!/usr/bin/env bash

set -euo pipefail

for arg in "$@"; do
    file -L "$BINARY" | grep -q "$arg" || (echo "Binary $BINARY does not have '$arg' in its file info: $(file -L "$BINARY")" && exit 1)
done

if [[ -n "${SHOULD_RUN:-}" ]]; then
    if ! "$BINARY"; then
        echo "Binary $BINARY failed to run"
        exit 1
    fi
else
    echo "Skipping execution of $BINARY as SHOULD_RUN is not set"
fi

echo "All tests passed"

EOF
""",
        },
        {
            "name": "Generate release archive",
            "run": f"./deterministic-tar.sh {output_path} WORKSPACE MODULE.bazel toolchains_musl.bzl toolchains.bzl repositories.bzl BUILD.bazel bcr_test/.bazelrc bcr_test/MODULE.bazel bcr_test/BUILD.bazel bcr_test/binary_test.sh",
        },
        # Keep the BCR tests at the end since they modify the files included in the release archive.
        {
            "name": "Run BCR tests",
            "run": f"""sed -i "s|https://github.com/bazel-contrib/musl-toolchain/releases/download/{version}/|file://$(pwd)/|g" repositories.bzl
cd bcr_test
bazel test ...
""",
        },
    ]



def upload_release_archive_artifact(filename):
    return {
        "name": "Upload release archive",
        "uses": "actions/upload-release-asset@v1",
        "env": {
            "GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}",
        },
        "with": {
            "upload_url": "${{ steps.create_release.outputs.upload_url }}",
            "asset_name": filename,
            "asset_path": filename,
            "asset_content_type": "application/gzip",
        },
    }


def generate_release_body(release_body_path, release_archive_path, version):
    return {
        "name": "Generate release body",
        "run": f"sha256=$(sha256sum {release_archive_path} | awk '{{print $1}}') ; url='{download_url_for(release_archive_path, version)}' ; version='{version}'; sed -e \"s#{{sha256}}#${{sha256}}#g\" -e \"s#{{url}}#${{url}}#g\" -e \"s|{{version}}|${{version#v}}|g\" release.txt.template > {release_body_path}",
    }


# Don't generate alias/anchors in the yaml, as it makes it harder to read at a glance.
# Given we're generating the yaml anyway, we strongly want to optimise for readability of the yaml over the
# maintainability of editing it.
class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def write_generated_header(file):
    file.write("# This file was generated by running ./generate-actions.py - it should not be manually modified\n\n")


def make_jobs(release, version):
    jobs = {
        "check-generated": {
            "runs-on": "ubuntu-24.04",
            "steps": [
                checkout,
                check_generated_files,
            ],
        },
    }

    source_machines = [
        (OS.Linux, Architecture.X86_64, linux_x86_64_runner),
        (OS.Linux, Architecture.ARM64, linux_aarch64_runner),
        (OS.MacOS, Architecture.X86_64, darwin_x86_64_runner),
        (OS.MacOS, Architecture.ARM64, darwin_aarch64_runner),
    ]

    target_os = OS.Linux
    target_machines = [
        (Architecture.X86_64, linux_x86_64_runner),
        (Architecture.ARM64, linux_aarch64_runner),
    ]

    releasable_artifacts = []
    test_build_jobs = defaultdict(dict)
    test_jobs = []

    for target_arch, target_runner in target_machines:
        for source_os, source_arch, source_runner in source_machines:
            build_job_name = (
                f"{source_os.for_musl}-{source_arch.for_musl}-{target_arch.for_musl}"
            )
            musl_filename = musl_filename_without_extension(source_os, source_arch, target_arch) + ".tar.gz"
            jobs[build_job_name] = source_runner.top_level_properties | {
                "needs": ["check-generated"],
                "steps": source_runner.build_setup_steps
                         + [
                             checkout,
                         ]
                         + [
                             {
                                 "name": "Build musl",
                                 "run": f"./build.sh {target_arch.for_musl}",
                             },
                             upload(musl_filename, os.path.join("output", musl_filename)),
                         ]
            }
            releasable_artifacts.append(
                ReleasableArtifact(
                    build_job_name=build_job_name,
                    source_os=source_os,
                    source_arch=source_arch,
                    target_os=target_os,
                    target_arch=target_arch,
                    musl_filename=musl_filename,
                )
            )

            test_build_job_name = f"{source_os.for_musl}-{source_arch.for_musl}-{target_arch.for_musl}-test-build"
            test_build_filename = f"test-binary-platform-{source_arch.for_musl}-{source_os.for_musl}-target-{target_arch.for_musl}-linux-musl"
            jobs[test_build_job_name] = source_runner.top_level_properties | {
                "needs": [build_job_name],
                "steps": source_runner.test_setup_steps + [
                    checkout,
                    download(musl_filename),
                    install_bazel(source_os, source_arch),
                    generate_builder_workspace_file(source_os, source_arch, target_arch),
                    generate_builder_workspace_config_build_file(
                        source_os, source_arch, target_arch
                    ),
                ] + ([
                    {
                        "name": "Test with musl",
                        "run": "cd test-workspaces/builder && bazel test //:test",
                    },
                    {
                        "name": "Test with musl (static linking)",
                        "run": "cd test-workspaces/builder && bazel test //:test --dynamic_mode=off",
                    },
                ] if source_os == OS.Linux and source_arch == target_arch else []) +
                [
                    {
                        "name": "Build with musl",
                        "run": "cd test-workspaces/builder && bazel build //:binary",
                    },
                    {
                        "name": "Move test binary",
                        "run": f"mkdir output && cp test-workspaces/builder/bazel-bin/binary output/{test_build_filename}",
                    },
                    upload(
                        test_build_filename, os.path.join("output", test_build_filename)
                    ),
                ],
            }
            test_build_jobs[target_arch][(source_os, source_arch)] = {
                "job_name": test_build_job_name,
                "output": test_build_filename,
            }

        if not target_runner:
            continue
        test_job_name = f"test-{target_arch.for_musl}"
        test_jobs.append(test_job_name)
        jobs[test_job_name] = target_runner.top_level_properties | {
            "needs": [
                test_build_job["job_name"]
                for _, test_build_job in test_build_jobs[target_arch].items()
            ],
            "steps": target_runner.test_setup_steps + [
                         checkout,
                     ]
                     + [
                         download(test_build_job["output"])
                         for _, test_build_job in test_build_jobs[target_arch].items()
                     ]
                     + [
                         install_bazel(target_os, target_arch),
                         generate_tester_workspace_file(test_build_jobs[target_arch]),
                         {
                             "run": "cd test-workspaces/tester && CC=/bin/false bazel test ... --test_output=all",
                         },
                     ],
        }


    if release:
        release_body_path = "release-notes.txt"
        release_archive_path = f"musl_toolchain-{version}.tar.gz"
        jobs["release"] = {
            "runs-on": "ubuntu-24.04",
            "needs": [job.build_job_name for job in releasable_artifacts] + test_jobs,
            "steps": [
                         checkout,
                         {
                             "run": "sudo ln -s /usr/bin/tar /usr/bin/gnutar",
                         },
                     ]
                     + [download(artifact.musl_filename) for artifact in releasable_artifacts]
                     + generate_release_archive(releasable_artifacts, release_archive_path, version)
                     + [
                         generate_release_body(release_body_path, release_archive_path, version),
                     ]
                     + [
                         {
                             "id": "create_release",
                             "name": "Create release",
                             "uses": "softprops/action-gh-release@v1",
                             "env": {
                                 "GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}",
                             },
                             "with": {
                                 "generate_release_notes": True,
                                 "tag_name": version,
                                 "body_path": release_body_path,
                                 "target_commitish": "${{ github.base_ref }}",
                             },
                         },
                         upload_release_archive_artifact(release_archive_path),
                     ]
                     + [
                         upload_release_archive_artifact(artifact.musl_filename)
                         for artifact in releasable_artifacts
                     ],
        }
        jobs["publish"] = {
            "needs": ["release"],
            "uses": "./.github/workflows/publish.yaml",
            "with": {
                "tag_name": version,
            },
            "secrets": {
                "BCR_PUBLISH_TOKEN": "${{ secrets.BCR_PUBLISH_TOKEN }}",
            },
        }
    return jobs


def main():
    output_dir = os.path.join(os.path.dirname(__file__), ".github", "workflows")
    with open(os.path.join(os.path.join(output_dir, "build.yaml")), "w") as f:
        actions_config = {
            "name": "PR",
            "on": {
                "pull_request": None,
                "workflow_dispatch": None,
            },
            "jobs": make_jobs(release=False, version="unreleased"),
        }
        write_generated_header(f)
        f.write(yaml.dump(actions_config, sort_keys=False, Dumper=NoAliasDumper))

    with open(os.path.join(os.path.join(output_dir, "release.yaml")), "w") as f:
        actions_config = {
            "name": "Release",
            "on": {
                "workflow_dispatch": None,
                "push": {
                    "tags": [
                        "*",
                    ]
                }
            },
            "permissions": {
                "id-token": "write",
                "attestations": "write",
                "contents": "write",
            },
            "jobs": make_jobs(release=True, version="${{github.ref_name}}"),
        }
        write_generated_header(f)
        f.write(yaml.dump(actions_config, sort_keys=False, Dumper=NoAliasDumper))


if __name__ == "__main__":
    main()
