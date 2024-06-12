import os
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

import yaml

checkout = {
    "name": "Checkout repo",
    "uses": "actions/checkout@v3",
}


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
    setup_steps: List[Dict[str, Any]]


def install_bazel(os: OS, arch: Architecture):
    match os:
        case OS.Linux:
            return {
                "name": "Download bazelisk as bazel",
                "run": f"curl --fail -L -o /usr/local/bin/bazel https://github.com/bazelbuild/bazelisk/releases/download/v1.18.0/bazelisk-{os.for_bazel_download}-{arch.for_bazel_download} && chmod 0755 /usr/local/bin/bazel",
            }
        case OS.MacOS:
            return {
                "name": "Skipping downloading bazelisk - already installed",
                "run": "bazel --version",
            }


linux_x86_64_runner = BaseRunner(
    top_level_properties={
        "runs-on": "ubuntu-latest",
        "container": "centos:centos8",
    },
    setup_steps=[
        {
            "run": "sed -i 's|mirrorlist|#mirrorlist|g' /etc/yum.repos.d/CentOS-*",
        },
        {
            "run": "sed -i 's|#baseurl=http://mirror.centos.org|baseurl=http://vault.centos.org|g' /etc/yum.repos.d/CentOS-*",
        },
        {
            "run": "yum install -y bzip2 git make patch wget",
        },
        {
            "run": 'dnf group install -y "Development Tools"',
        },
        {
            "run": "ln -s /usr/bin/tar /usr/bin/gnutar",
        },
    ],
)

_setup_darwin_steps = [
    {
        "run": "brew install wget md5sha1sum gnu-tar",
    },
]

darwin_x86_64_runner = BaseRunner(
    top_level_properties={
        "runs-on": "macos-11",
    },
    setup_steps=_setup_darwin_steps,
)

darwin_aarch64_runner = BaseRunner(
    top_level_properties={
        "runs-on": "macos-14",
    },
    setup_steps=_setup_darwin_steps,
)


def upload(name, path):
    return {
        "name": f"Upload {name}",
        "uses": "actions/upload-artifact@v3",
        "with": {
            "name": name,
            "path": path,
            "if-no-files-found": "error",
        },
    }


def download(name):
    return {
        "name": f"Download {name}",
        "uses": "actions/download-artifact@v3",
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


def generate_builder_workspace_config_build_file(
    source_os: OS, source_arch: Architecture, target_arch: Architecture
):
    content = generate_toolchain("musl_toolchain", source_arch, source_os, target_arch, wrap_in_triple_quotes=False)
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


def generate_builder_workspace_file(source_os, musl_filename):
    content = f"""load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

http_archive(
    name = "musl_toolchain",
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
    repo_name, source_arch: Architecture, source_os: OS, target_arch: Architecture, wrap_in_triple_quotes: bool, extra_exec_compatible_expr: str = "", extra_target_compatible_expr: str = ""
):
    if not wrap_in_triple_quotes and (extra_exec_compatible_expr or extra_target_compatible_expr):
        raise RuntimeError("Can't set extra_{exec,target}_compatible_expr if not wrap_in_triple_quotes")

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

    to_return += f""",
    toolchain = "@{repo_name}//:musl_toolchain",
    toolchain_type = "@bazel_tools//tools/cpp:toolchain_type",
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
bazel_dep(name = "platforms", version = "0.0.9")

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

    load_musl_toolchains(
        extra_exec_compatible_with = [str(label) for label in extra_exec_compatible_with],
        extra_target_compatible_with = [str(label) for label in extra_target_compatible_with],
    )

    if bazel_features.external_deps.extension_metadata_has_reproducible:
        return module_ctx.extension_metadata(reproducible = True)
    else:
        return None

_config = tag_class(
    attrs = {
        "extra_exec_compatible_with": attr.label_list(),
        "extra_target_compatible_with": attr.label_list(),
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
            "name": "Generate toolchains.bzl",
            "run": f"""touch BUILD.bazel

cat >toolchains.bzl <<EOF
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
    }},
)

def load_musl_toolchains(extra_exec_compatible_with=[], extra_target_compatible_with=[]):
{textwrap.indent(http_archives, "    ")}

    toolchain_repo(
        name = "musl_toolchains_hub",
        extra_exec_compatible_with = extra_exec_compatible_with,
        extra_target_compatible_with = extra_target_compatible_with,
    )
EOF
""",
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

bazel_dep(name = "aspect_bazel_lib", version = "2.7.7")

toolchains_musl = use_extension("@toolchains_musl//:toolchains_musl.bzl", "toolchains_musl", dev_dependency = True)
toolchains_musl.config(
    extra_target_compatible_with = ["//:musl_on"],
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

package(default_visibility = ["//visibility:public"])

genrule(
    name = "generate_source",
    outs = ["main.cc"],
    cmd = """cat >$@ <<EOF
#include <stdio.h>

int main(void) {
  printf("Built on $$(uname) $$(uname -m)\\\\n");
  return 0;
}
EOF
""",
)

cc_binary(
    name = "binary",
    srcs = ["main.cc"],
    tags = ["manual"],
)

platform_transition_binary(
    name = "binary_linux_x86_64",
    binary = ":binary",
    target_platform = ":linux_x86_64",
)

platform_transition_binary(
    name = "binary_linux_aarch64",
    binary = ":binary",
    target_platform = ":linux_aarch64",
)

sh_test(
    name = "binary_test",
    srcs = ["binary_test.sh"],
    data = [
        ":binary_linux_x86_64",
        ":binary_linux_aarch64",
    ],
    env = {
        "BINARY_LINUX_X86_64": "$(rootpath :binary_linux_x86_64)",
        "BINARY_LINUX_AARCH64": "$(rootpath :binary_linux_aarch64)",
    },
)

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
EOF2
''',
        },
        {
            "name": "Generate bcr_test/binary_test.sh",
            "run": f"""mkdir -p bcr_test
touch bcr_test/binary_test.sh
chmod +x bcr_test/binary_test.sh

cat >bcr_test/binary_test.sh <<'EOF'
#!/usr/bin/env bash

set -euo pipefail

file -L "$BINARY_LINUX_X86_64" | grep 'statically linked' || (echo "Binary $BINARY_LINUX_X86_64 is not statically linked: $(file -L "$BINARY_LINUX_X86_64")" && exit 1)
file -L "$BINARY_LINUX_X86_64" | grep 'x86-64' || (echo "Binary $BINARY_LINUX_X86_64 is not x86-64: $(file -L "$BINARY_LINUX_X86_64")" && exit 1)

file -L "$BINARY_LINUX_AARCH64" | grep 'statically linked' || (echo "Binary $BINARY_LINUX_AARCH64 is not statically linked: $(file -L "$BINARY_LINUX_AARCH64")" && exit 1)
file -L "$BINARY_LINUX_AARCH64" | grep 'aarch64' || (echo "Binary $BINARY_LINUX_AARCH64 is not aarch64: $(file -L "$BINARY_LINUX_AARCH64")" && exit 1)

echo "All tests passed"
EOF
""",
        },
        {
            "name": "Generate release archive",
            "run": f"./deterministic-tar.sh {output_path} WORKSPACE MODULE.bazel toolchains_musl.bzl toolchains.bzl repositories.bzl BUILD.bazel bcr_test/MODULE.bazel bcr_test/BUILD.bazel bcr_test/binary_test.sh",
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
    jobs = {}

    source_machines = [
        (OS.Linux, Architecture.X86_64, linux_x86_64_runner),
        (OS.MacOS, Architecture.X86_64, darwin_x86_64_runner),
        (OS.MacOS, Architecture.ARM64, darwin_aarch64_runner),
    ]

    target_os = OS.Linux
    target_arches = [
        Architecture.X86_64,
        Architecture.ARM64,
    ]

    releasable_artifacts = []
    test_build_jobs = defaultdict(dict)
    test_jobs = []

    for target_arch in target_arches:
        for source_os, source_arch, runner in source_machines:
            build_job_name = (
                f"{source_os.for_musl}-{source_arch.for_musl}-{target_arch.for_musl}"
            )
            musl_filename = f"musl-1.2.3-platform-{source_arch.for_musl}-{source_os.for_musl}-target-{target_arch.for_musl}-linux-musl.tar.gz"
            jobs[build_job_name] = runner.top_level_properties | {
                "steps": [
                             checkout,
                         ]
                         + runner.setup_steps
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

            # TODO: Make this unconditional when GitHub Actions supports Linux arm64 runners
            # For now we just release these binaries without testing them
            # (Currently in private beta: https://github.blog/changelog/2023-10-30-accelerate-your-ci-cd-with-arm-based-hosted-runners-in-github-actions/)
            # See https://github.com/actions/runner-images/issues/5631
            if target_arch != Architecture.X86_64:
                continue
            test_build_job_name = f"{source_os.for_musl}-{source_arch.for_musl}-{target_arch.for_musl}-test-build"
            test_build_filename = f"test-binary-platform-{source_arch.for_musl}-{source_os.for_musl}-target-{target_arch.for_musl}-linux-musl"
            jobs[test_build_job_name] = runner.top_level_properties | {
                "needs": [build_job_name],
                "steps": [
                    checkout,
                    download(musl_filename),
                    install_bazel(source_os, source_arch),
                    generate_builder_workspace_file(source_os, musl_filename),
                    generate_builder_workspace_config_build_file(
                        source_os, source_arch, target_arch
                    ),
                    {
                        "name": "Build test binary and test with musl",
                        "run": "cd test-workspaces/builder && BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1 bazel build //:binary //:test --platforms=//config:platform --extra_toolchains=//config:musl_toolchain --incompatible_enable_cc_toolchain_resolution",
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

        # TODO: Make this unconditional when GitHub Actions supports Linux arm64 runners
        # For now we just release these binaries without testing them
        # (Currently in private beta: https://github.blog/changelog/2023-10-30-accelerate-your-ci-cd-with-arm-based-hosted-runners-in-github-actions/)
        # See https://github.com/actions/runner-images/issues/5631
        if target_arch != Architecture.X86_64:
            continue
        test_job_name = f"test-{target_arch.for_musl}"
        test_jobs.append(test_job_name)
        jobs[test_job_name] = linux_x86_64_runner.top_level_properties | {
            "needs": [
                test_build_job["job_name"]
                for _, test_build_job in test_build_jobs[target_arch].items()
            ],
            "steps": [
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
            "runs-on": "ubuntu-latest",
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
            "jobs": make_jobs(release=True, version="${{github.ref_name}}"),
        }
        write_generated_header(f)
        f.write(yaml.dump(actions_config, sort_keys=False, Dumper=NoAliasDumper))


if __name__ == "__main__":
    main()
