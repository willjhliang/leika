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
copyright = "2026 Leika"  # noqa: A001
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
# The homepage is the README, whose H1 is the centered logo-and-wordmark lockup
# -- raw HTML, because neither GitHub nor PyPI will center a Markdown heading.
# MyST cannot see a heading it did not parse, so it reads the page as starting
# at `## Quickstart` and warns; under the `-W` the docs build uses, that warning
# is fatal. The H1 is there, so the check is answering about the wrong thing.
suppress_warnings = ["myst.header"]

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
html_title = project
html_static_path = ["_static"]
html_css_files = ["leika.css"]
# The sidebar brand becomes the same lockup the homepage heads with. The
# wordmark beside it is `html_title`, which `leika.css` sets in Almarai and
# lowercases to match the mark -- the title itself stays capitalized, since it
# is also what the browser tab and the search index read.
html_logo = "_static/leika.svg"


def _drop_icon_attribute_list(app, what, name, obj, options, lines):
    """Strip the generated ``Attributes:`` block from ``leika.Icon``.

    ``_icons_enum.py`` documents every Lucide icon as a docstring attribute.
    Rendering all ~2000 of them cost a 1.3 MB page and put 1998 ``Icon.*``
    entries into the global and search indices, burying the rest of the API.
    ``docs/api/icons.rst`` points at lucide.dev instead.
    """
    if name != "leika.Icon":
        return
    for index, line in enumerate(lines):
        if line.strip() == "Attributes:":
            del lines[index:]
            break


def setup(app):
    # Run ahead of napoleon, which connects to this event at the default
    # priority of 500 and would otherwise have already expanded the block into
    # individual attribute directives.
    app.connect("autodoc-process-docstring", _drop_icon_attribute_list, priority=400)
