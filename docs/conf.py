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
# Lowercase like the wordmark: the browser tab is a place the brand is drawn.
# `project` stays capitalized for the places it is prose ("Leika documentation").
html_title = "leika"
html_static_path = ["_static"]
# shadcn.css defines the client's design tokens and the chrome overrides;
# leika.css is the brand lockup, which consumes those tokens.
html_css_files = ["shadcn.css", "leika.css"]

# Furo's defaults, pinned explicitly. Both are contrast-audited palettes that
# read neutral once the bridge below moves the code surface onto the client's
# muted gray; syntax stays chromatic, as it does in any shadcn app.
pygments_style = "a11y-light"
pygments_dark_style = "native"

# Furo's own variables, re-pointed at the client's design tokens (defined in
# shadcn.css). Values are var() references, so light and dark need no separate
# dicts -- the tokens flip themselves. The SAME dict is deliberately assigned
# to both slots: furo's dark stylesheet re-declares every variable at
# `body[data-theme="dark"]` specificity, so a bridge present only in the light
# slot would be clobbered the moment the reader switches schemes.
_shadcn_bridge = {
    # Type: Geist, the client's one face, with the client's literal 13px/11px
    # component sizes pinned absolute so they cannot compound off the article
    # font size set in shadcn.css.
    "font-stack": '"Geist Variable", ui-sans-serif, system-ui, -apple-system, sans-serif',
    "font-stack--headings": "var(--font-stack)",
    "font-stack--monospace": (
        'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", '
        '"Courier New", monospace'
    ),
    "code-font-size": "0.8125rem",
    "api-font-size": "0.8125rem",
    "sidebar-item-font-size": "0.8125rem",
    "sidebar-search-input-font-size": "0.8125rem",
    "admonition-font-size": "0.8125rem",
    "admonition-title-font-size": "0.8125rem",
    "toc-font-size": "0.75rem",
    "sidebar-caption-font-size": "0.6875rem",
    "toc-title-font-size": "0.6875rem",
    # Foregrounds and surfaces.
    "color-foreground-primary": "var(--foreground)",
    "color-foreground-secondary": "var(--muted-foreground)",
    "color-foreground-muted": "var(--muted-foreground)",
    "color-foreground-border": "var(--border)",
    "color-background-primary": "var(--background)",
    "color-background-secondary": "var(--muted)",
    "color-background-hover": "var(--accent)",
    "color-background-hover--transparent": "transparent",
    "color-background-border": "var(--border)",
    "color-background-item": "var(--muted)",
    "color-content-foreground": "var(--foreground)",
    # Links behave like the client's icon buttons: muted at rest, the full
    # foreground on hover. No brand blue, no visited purple; the underline
    # travels with the text.
    "color-brand-primary": "var(--foreground)",
    "color-brand-content": "var(--foreground)",
    "color-brand-visited": "var(--foreground)",
    "color-link": "var(--muted-foreground)",
    "color-link--hover": "var(--foreground)",
    "color-link--visited": "var(--muted-foreground)",
    "color-link--visited--hover": "var(--foreground)",
    "color-link-underline": "currentColor",
    "color-link-underline--hover": "currentColor",
    "color-link-underline--visited": "currentColor",
    "color-link-underline--visited--hover": "currentColor",
    # Code sits on the client's muted surface. These two override the values
    # furo injects from the pygments palettes, which are emitted earlier in
    # the same inline style block.
    "color-inline-code-background": "var(--muted)",
    "color-code-background": "var(--muted)",
    "color-code-foreground": "var(--foreground)",
    # Search-match marks. Jump targets are furo's own (`#ffc` light,
    # `#333300` dark) -- deliberately not bridged.
    "color-highlighted-background": "var(--border)",
    "color-highlighted-text": "var(--foreground)",
    # API signatures: flat muted chips, names in foreground rather than
    # furo's red, everything structural in muted-foreground. Deprecation and
    # removal keep the palette's one chroma.
    "color-problematic": "var(--foreground)",
    "color-api-background": "var(--muted)",
    "color-api-background-hover": "var(--muted)",
    "color-api-overall": "var(--muted-foreground)",
    "color-api-name": "var(--foreground)",
    "color-api-pre-name": "var(--muted-foreground)",
    "color-api-paren": "var(--muted-foreground)",
    "color-api-keyword": "var(--muted-foreground)",
    "color-api-added": "var(--foreground)",
    "color-api-added-border": "var(--border)",
    "color-api-changed": "var(--foreground)",
    "color-api-changed-border": "var(--border)",
    "color-api-deprecated": "var(--destructive)",
    "color-api-deprecated-border": "color-mix(in oklch, var(--destructive) 40%, transparent)",
    "color-api-removed": "var(--destructive)",
    "color-api-removed-border": "color-mix(in oklch, var(--destructive) 40%, transparent)",
    # Admonitions as shadcn alerts: no filled title bars, icon and title in
    # foreground -- except the warning family, which stays destructive.
    "color-admonition-background": "var(--card)",
    "color-admonition-title": "var(--foreground)",
    "color-admonition-title-background": "transparent",
    "color-admonition-title--note": "var(--foreground)",
    "color-admonition-title--hint": "var(--foreground)",
    "color-admonition-title--tip": "var(--foreground)",
    "color-admonition-title--important": "var(--foreground)",
    "color-admonition-title--seealso": "var(--foreground)",
    "color-admonition-title--admonition-todo": "var(--foreground)",
    "color-admonition-title--warning": "var(--destructive)",
    "color-admonition-title--caution": "var(--destructive)",
    "color-admonition-title--danger": "var(--destructive)",
    "color-admonition-title--attention": "var(--destructive)",
    "color-admonition-title--error": "var(--destructive)",
    "color-admonition-title-background--note": "transparent",
    "color-admonition-title-background--hint": "transparent",
    "color-admonition-title-background--tip": "transparent",
    "color-admonition-title-background--important": "transparent",
    "color-admonition-title-background--seealso": "transparent",
    "color-admonition-title-background--admonition-todo": "transparent",
    "color-admonition-title-background--warning": "transparent",
    "color-admonition-title-background--caution": "transparent",
    "color-admonition-title-background--danger": "transparent",
    "color-admonition-title-background--attention": "transparent",
    "color-admonition-title-background--error": "transparent",
    "color-topic-title": "var(--foreground)",
    "color-topic-title-background": "transparent",
    # Tables: horizontal hairlines only.
    "color-table-header-background": "transparent",
    "color-table-border": "var(--border)",
    # Cards carry the client's ring-foreground/10 border.
    "color-card-background": "var(--card)",
    "color-card-border": "color-mix(in oklch, var(--foreground) 10%, transparent)",
    "color-card-marginals-background": "var(--muted)",
    # Header, sidebar, and toc chrome. A flat accent in the hover slot
    # replaces furo's linear-gradient trick outright.
    "color-header-background": "var(--background)",
    "color-header-border": "var(--border)",
    "color-header-text": "var(--foreground)",
    "color-sidebar-background": "var(--sidebar)",
    "color-sidebar-background-border": "var(--sidebar-border)",
    "color-sidebar-brand-text": "var(--foreground)",
    "color-sidebar-caption-text": "var(--muted-foreground)",
    "color-sidebar-link-text": "var(--muted-foreground)",
    "color-sidebar-link-text--top-level": "var(--muted-foreground)",
    "color-sidebar-item-background--current": "var(--accent)",
    "color-sidebar-item-background--hover": "var(--accent)",
    "color-sidebar-item-expander-background--hover": "var(--accent)",
    "color-sidebar-search-text": "var(--foreground)",
    "color-sidebar-search-background": "transparent",
    "color-sidebar-search-background--focus": "transparent",
    "color-sidebar-search-border": "var(--input)",
    "color-sidebar-search-icon": "var(--muted-foreground)",
    "color-toc-background": "var(--background)",
    "color-toc-title-text": "var(--muted-foreground)",
    "color-toc-item-text": "var(--muted-foreground)",
    "color-toc-item-text--hover": "var(--foreground)",
    "color-toc-item-text--active": "var(--foreground)",
    # GUI labels as muted badge chips.
    "color-guilabel-background": "var(--muted)",
    "color-guilabel-border": "var(--border)",
    "color-guilabel-text": "var(--foreground)",
}
html_theme_options = {
    "light_css_variables": _shadcn_bridge,
    "dark_css_variables": _shadcn_bridge,
    # No view/edit buttons floating over the article. The theme toggle that
    # shared that corner moves to the footer via _templates/page.html.
    "top_of_page_buttons": [],
}
# The sidebar brand becomes the same lockup the homepage heads with. The
# wordmark beside it is `html_title`, set in Almarai by `leika.css` and
# already lowercase, so the CSS lowercasing there is now a no-op kept for
# anything else that renders the title.
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
