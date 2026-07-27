API reference
=============

Every name documented here is importable directly from ``leika``, or from the
``leika.theme`` and ``leika.uplot`` subpackages. Modules with a leading
underscore are implementation detail and are not part of the public surface.

``leika.infra`` holds the websocket and HTTP plumbing that the rest of the
package runs on. It is importable, but it is not covered here and is generally
only useful when building a web application from scratch rather than when using
Leika.

.. toctree::
   :maxdepth: 2

   server
   panes
   gui
   gui_handles
   icons
   theme
   uplot
