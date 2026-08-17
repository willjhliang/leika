Pages
=====

.. currentmodule:: leika

Pages partition a workspace's panes and browser-managed pane layouts. The GUI
and control dock remain shared across the workspace.

Every :class:`Server` creates a default page. ``Server(label=...)`` names that
page, or it is named ``Main`` when no label is supplied. ``server.panes`` is a
compatibility alias for ``server.pages.default.panes``.

Create another page with ``server.pages.add(name, page_id=...)`` and add panes
through the returned page's ``panes`` API. Give persistent applications an
explicit page ID: page names are display text and may change, while the stable
ID keeps the browser layout attached to the same page.

Page collection
---------------

.. autoclass:: Pages
   :members:

Page
----

.. autoclass:: Page
   :members:

Types
-----

.. autodata:: PageId
