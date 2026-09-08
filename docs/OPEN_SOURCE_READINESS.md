# Open-source readiness

The repository is safe to share only when generated data, credentials, local runtime files, and machine-specific paths are excluded. Contributors must keep operational secrets in environment variables or the deployment secret store.

Before publishing, run the offline test suite, review tracked files for `.env` content and generated artifacts, and confirm that live execution remains disabled unless an operator explicitly enables it.
