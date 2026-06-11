# Changelog

## 0.1.4 - 2026-06-11

- Fixed installed-wheel startup for the embedded Pi runtime by materializing the
  locked npm dependency tree into a user cache when packaged artifacts omit
  `node_modules`.
- Added a per-runtime cache lock so concurrent first starts share one completed
  materialization instead of racing over the same cache target.
- Added an installed-artifact release check that builds the wheel, installs it
  into a clean virtual environment, and verifies the embedded Pi bridge reaches
  readiness.
- Included release helper scripts and the changelog in source distributions.
