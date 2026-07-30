"""Load and dump ``mkdocs.yml`` without choking on its ``!!python/name:`` tags.

MkDocs configs carry Python-object tags — e.g. the Mermaid superfences hook
``format: !!python/name:pymdownx.superfences.fence_code_format``. ``yaml.safe_load``
refuses those tags outright, and the plain ``yaml.dump`` used for nav rewrites
would drop them. This module round-trips the tag faithfully: it is parsed into a
lightweight :class:`_PyName` marker on load and re-emitted verbatim on dump, so
read-modify-write passes over the nav never disturb the rendering config.
"""

import yaml
from pathlib import Path

_PYNAME_TAG = "tag:yaml.org,2002:python/name:"


class _PyName:
    """Placeholder for a ``!!python/name:<dotted.name>`` scalar, preserved on dump."""

    def __init__(self, name: str):
        self.name = name


def _construct_pyname(loader, suffix, node):
    return _PyName(suffix)


def _represent_pyname(dumper, data):
    return dumper.represent_scalar(_PYNAME_TAG + data.name, "")


class _Loader(yaml.SafeLoader):
    pass


class _Dumper(yaml.SafeDumper):
    pass


_Loader.add_multi_constructor(_PYNAME_TAG, _construct_pyname)
_Dumper.add_representer(_PyName, _represent_pyname)


def load(mkdocs_yml: Path) -> dict:
    """Parse ``mkdocs.yml``, tolerating ``!!python/name:`` tags. Returns {} if empty."""
    return yaml.load(mkdocs_yml.read_text(encoding="utf-8"), Loader=_Loader) or {}


def dump(config: dict) -> str:
    """Serialise a config back to YAML, preserving ``!!python/name:`` tags."""
    return yaml.dump(config, Dumper=_Dumper, allow_unicode=True,
                     sort_keys=False, default_flow_style=False)
