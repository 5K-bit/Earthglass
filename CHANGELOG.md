# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-11-02

First tagged release. See [docs/releases/v0.4.0.md](docs/releases/v0.4.0.md).

### Added

- Release workflow: runs the full CI, checks the tag matches the package version and is on the default branch, builds the wheel and sdist, smoke-tests the wheel in a clean environment, and publishes a prerelease with SHA256SUMS.
- Apache-2.0 licence (MIT for QuietDrop, as declared in its `pyproject.toml`) and the AI-assistance note in the README.
