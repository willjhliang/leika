GUI
===

.. currentmodule:: leika

``Server.gui`` builds the control panel. Each ``add_*`` method returns a handle
whose ``value`` reflects the browser's current state.

Long control labels and dropdown options end in an ellipsis when they do not
fit; hover over the text to reveal the rest. This includes searchable dropdowns.
Button groups, toggles, and tabs wrap onto additional rows, truncating individual
labels only when they exceed the available width.

A form added with ``mini=True`` contains exactly one direct editable field. A
sibling display row, nested container, or second field is rejected before
either the field or the form is published; use a regular form for a larger
layout.

:meth:`GuiApi.add_html` inserts trusted raw HTML without sanitizing it.
Sanitize all untrusted content before passing it to this method.

.. autoclass:: GuiApi
   :members:

.. autoclass:: GuiContainer
   :members:

.. autoclass:: GuiVideoControlsHandle
   :members:

.. autoclass:: GuiPlaybackHandle
   :members:
   :inherited-members: update, remove

.. autoclass:: PlaybackState
   :members:

.. autoclass:: PlaybackEvent
   :members:
