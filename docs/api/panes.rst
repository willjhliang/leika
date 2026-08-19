Panes
=====

.. currentmodule:: leika

Panes are the workspace's content surfaces. Python owns pane existence,
content, visibility, and the initial placement hint; the browser owns the
user's arrangement after that.

Pane API
--------

.. autoclass:: Panes
   :members:

Handles
-------

.. autoclass:: PaneHandle
   :members:

.. autoclass:: ImagePaneHandle
   :members:
   :inherited-members:

.. autoclass:: MatplotlibPaneHandle
   :members:
   :inherited-members:

.. autoclass:: PlotlyPaneHandle
   :members:
   :inherited-members:

.. autoclass:: ViserPaneHandle
   :members:
   :inherited-members:

Layout
------

.. autoclass:: PaneGroup
   :members:

.. autoclass:: PaneGrid
   :members:

Types
-----

.. autodata:: PaneId

.. autodata:: ImageFit

.. autodata:: PaneLoading

.. autodata:: Placement
