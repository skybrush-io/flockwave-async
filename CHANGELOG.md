# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.1] - 2025-07-24

### Changed

- `race()`, `gather()` and `delayed()` were re-written using `anyio` so they
  can be used even in projects that do not use Trio. This should not be a
  breaking change for users of this library, hence the patch version bump.

## [2.1.0] - 2025-07-24

### Added

- Added `gather()` to collect the results of multiple asynchronous tasks
  simultaneously.

## [2.0.1] - 2025-04-20

This is the release that serves as a basis for changelog entries above. Refer
to the commit logs for changes affecting this version and earlier versions.
