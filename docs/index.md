```{include} ../README.md
:parser: myst
```

% `self` is Sphinx's name for the root page: the lockup above already links
% home, but a logo is not obviously a link; this entry is.
```{toctree}
:maxdepth: 2
:caption: Guides
:hidden:

Home <self>
examples
gallery
architecture
remote-access
development
```

% Flat on purpose: the API pages sit directly in the section rather than
% nested under an expandable entry, with the api/index prose reachable as
% "Overview". Its own toctree is gone -- a page in two toctrees is a
% warning, and -W makes warnings fatal.
```{toctree}
:maxdepth: 1
:caption: Reference
:hidden:

Overview <api/index>
api/server
api/panes
api/gui
api/gui_handles
api/icons
api/theme
```
