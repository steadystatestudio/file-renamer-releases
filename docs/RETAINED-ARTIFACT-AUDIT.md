# Audit-only branch

This branch adds read-only verification tooling for the already-built release
source `85f7139b2620bf5059968349b4580455a23966b1`. It is not a new application
release and does not rebuild, replace, upload, or publish release files.

The workflow downloads retained v2.0.2 Windows/Linux packages, verifies their
hashes against the exact readiness receipt, checks source/provenance and bundled
license/shared-library inventories, rejects runtime settings/history and private
Git history, then runs the same retained Linux GUI/preview-worker bytes on Ubuntu
24.04 using offscreen and X11/Xvfb. Windows execution remains covered by its native
release build. Job logs retain the bounded inventory and check results.

The release tag and the default branch continue to identify the reviewed
application source. Publication remains a separate human-reviewed action.
