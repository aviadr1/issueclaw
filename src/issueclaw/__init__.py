from importlib.metadata import version

# pyproject.toml is the single source of the version; the publish workflow
# checks the release tag against it.
__version__ = version("issueclaw")
