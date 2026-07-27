"""Sphinx configuration for the Leika documentation build.

Build locally with ``make docs`` from the repository root, which renders into
``docs/_build/html``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from leika import __version__  # noqa: E402

project = "Leika"
author = "Will Liang"
copyright = "2026, Will Liang"  # noqa: A001
release = __version__
version = __version__

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", ".DS_Store"]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# The narrative pages are Markdown so they stay readable on GitHub; the API
# reference is reStructuredText because autodoc directives take structured
# options that MyST would only pass through an eval-rst block anyway.
myst_enable_extensions = ["colon_fence", "deflist", "fieldlist"]
myst_heading_anchors = 3

autosummary_generate = True
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented_params"
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
}
# Plotly is an optional dependency; the docs builder installs only the base
# package plus the docs extra.
autodoc_mock_imports = ["plotly"]

napoleon_google_docstring = True
napoleon_numpy_docstring = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
}

html_theme = "furo"
html_title = f"Leika {release}"
html_static_path = ["_static"]
