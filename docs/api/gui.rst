GUI
===

.. currentmodule:: leika

``Server.gui`` builds the control panel. Each ``add_*`` method returns a handle
whose ``value`` reflects the browser's current state.

A mini form contains exactly one direct editable field. A sibling display row,
nested container, or second field is rejected before either the field or the
form is published; use a regular form for a larger layout.

:meth:`GuiApi.add_html` inserts trusted raw HTML without sanitizing it.
Sanitize all untrusted content before passing it to this method.

.. autoclass:: GuiApi
   :members:

.. autoclass:: GuiContainer
   :members:
