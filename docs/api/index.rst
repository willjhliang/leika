API reference
=============

Every name documented here is importable directly from ``leika``, or from the
``leika.theme`` subpackage. Modules with a leading underscore are
implementation detail and are not part of the public surface.

``leika.infra`` holds the websocket and HTTP plumbing that the rest of the
package runs on. It is importable, but it is not covered here and is generally
only useful when building a web application from scratch rather than when using
Leika.

.. The section's pages are listed by the root toctree in index.md, which
   names this page "Overview"; a second toctree here would double-reference
   them, which -W turns fatal.
