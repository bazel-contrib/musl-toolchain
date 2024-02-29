import os
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

import yaml

# TODO: Take this from a git tag.
version = "v0.1.0"

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
        "runs-on": "macos-13-xlarge",
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
    content = generate_toolchain("musl_toolchain", source_arch, source_os, target_arch)
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


# TODO: Work out if there's a magic variable we can use from GitHub Actions here.
def download_url_for(filename):
    return f"https://github.com/bazel-contrib/musl-toolchain/releases/download/{version}/{filename}"


def generate_toolchain(
    repo_name, source_arch: Architecture, source_os: OS, target_arch: Architecture
):
    return f"""toolchain(
    name = "{repo_name}",
    exec_compatible_with = [
        "@platforms//cpu:{source_arch.for_bazel_platform}",
        "@platforms//os:{source_os.for_bazel_platform}",
    ],
    target_compatible_with = [
        "@platforms//cpu:{target_arch.for_bazel_platform}",
        "@platforms//os:linux",
    ],
    toolchain = "@{repo_name}//:musl_toolchain",
    toolchain_type = "@bazel_tools//tools/cpp:toolchain_type",
)
"""


def http_archive(name, sha256, url):
    return f"""http_archive(
    name = "{name}",
    sha256 = "{sha256}",
    url = "{url}",
)
"""


def generate_release_archive(toolchain_infos, output_path):
    toolchain_build_contents = "\n".join(
        [
            generate_toolchain(
                artifact.repo_name,
                artifact.source_arch,
                artifact.source_os,
                artifact.target_arch,
            )
            for artifact in toolchain_infos
        ]
    )

    http_archives = "\n".join(
        [
            http_archive(
                name=artifact.repo_name,
                sha256=f"$(sha256sum {artifact.musl_filename} | awk '{{print $1}}')",
                url=download_url_for(artifact.musl_filename),
            )
            for artifact in toolchain_infos
        ]
    )

    return [
        {
            "name": "Generate toolchains.bzl",
            "run": f"""cat >BUILD.bazel <<EOF
{toolchain_build_contents}
EOF

cat >toolchains.bzl <<EOF
def register_musl_toolchains():
    native.register_toolchains("@musl_toolchains//:all")
EOF
""",
        },
        {
            "name": "Generate repositories.bzl",
            "run": f"""cat >repositories.bzl <<EOF
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

def load_musl_toolchains():
{textwrap.indent(http_archives, "    ")}
EOF
""",
        },
        {
            "name": "Generate release archive",
            "run": f"./deterministic-tar.sh {output_path} toolchains.bzl repositories.bzl BUILD.bazel",
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


def generate_release_body(release_body_path, release_archive_path):
    return {
        "name": "Generate release body",
        "run": f"sha256=$(sha256sum {release_archive_path} | awk '{{print $1}}') ; url='{download_url_for(release_archive_path)}' ; sed -e \"s#{{sha256}}#${{sha256}}#g\" -e \"s#{{url}}#${{url}}#g\" release.txt.template > {release_body_path}",
    }


# Don't generate alias/anchors in the yaml, as it makes it harder to read at a glance.
# Given we're generating the yaml anyway, we strongly want to optimise for readability of the yaml over the
# maintainability of editing it.
class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def write_generated_header(file):
    file.write("# This file was generated by running ./generate-actions.py - it should not be manually modified\n\n")

def main():
    jobs = {}

    source_machines = [
        (OS.Linux, Architecture.X86_64, linux_x86_64_runner),
        (OS.MacOS, Architecture.X86_64, darwin_x86_64_runner),
        # TODO: Re-enable arm64 builds when we work out the billing situation (these runners cost money to run on GitHub Actions).
        # We may choose to bill this to bazel-contrib, or to try to move to bazel-ci.
        #(OS.MacOS, Architecture.ARM64, darwin_aarch64_runner),
    ]

    target_os = OS.Linux
    target_arches = [
        Architecture.X86_64,
        # TODO: GitHub Actions doesn't currently have a way of running Linux ARM64, so we can't currently test these.
        # For now, we won't build them either, but if needed, we could build and release these untested binaries.
        # See https://github.com/actions/runner-images/issues/5631
        # Architecture.ARM64,
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
                        "name": "Build test binary with musl",
                        "run": "cd test-workspaces/builder && BAZEL_DO_NOT_DETECT_CPP_TOOLCHAIN=1 bazel build //:binary --platforms=//config:platform --extra_toolchains=//config:musl_toolchain --incompatible_enable_cc_toolchain_resolution",
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

    output_dir = os.path.join(os.path.dirname(__file__), ".github", "workflows")
    with open(os.path.join(os.path.join(output_dir, "build.yaml")), "w") as f:
        actions_config = {
            "name": "PR",
            "on": {
                "pull_request": None,
                "workflow_dispatch": None,
            },
            "jobs": jobs,
        }
        write_generated_header(f)
        f.write(yaml.dump(actions_config, sort_keys=False, Dumper=NoAliasDumper))

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
        + generate_release_archive(releasable_artifacts, release_archive_path)
        + [
            generate_release_body(release_body_path, release_archive_path),
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

    with open(os.path.join(os.path.join(output_dir, "release.yaml")), "w") as f:
        actions_config = {
            "name": "Release",
            "on": {
                # TODO: Make this trigger on tag push
                "workflow_dispatch": None,
            },
            "jobs": jobs,
        }
        write_generated_header(f)
        f.write(yaml.dump(actions_config, sort_keys=False, Dumper=NoAliasDumper))


if __name__ == "__main__":
    main()
