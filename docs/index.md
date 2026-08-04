```{include} ../README.md
:parser: myst
```

% Keep an explicit Home entry in addition to the linked logo.
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

% The root owns the API toctree so pages are not referenced twice.
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
