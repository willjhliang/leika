GUI handles
===========

.. currentmodule:: leika

Handles are returned by the ``leika.GuiApi.add_*`` methods. Input handles carry
a ``value`` and support ``on_update`` callbacks; container handles can be used
as context managers to scope the controls added inside them.

Assigning a property or calling ``update(...)`` validates the new state and
publishes it in one message; Python commits it only once that message is
queued. Removal is terminal: updates and new callback registrations raise
``RuntimeError``, while reads return the last state. Removing a container
removes every descendant. Repeating an explicit removal emits a warning and is
otherwise a harmless no-op. The same lifecycle applies to commands, modals, and
notifications.

Dynamic dropdowns
-----------------

Both plain and searchable dropdowns support ``on_open``. Use it to rescan a
changing source when the menu opens, with ``on_update`` to apply a selection::

    checkpoint = server.gui.add_dropdown("Checkpoint", ("Choose a checkpoint",))

    @checkpoint.on_open
    def refresh(event):
        checkpoint.options = tuple(p.name for p in run_dir.glob("*.pt")) or (
            "Choose a checkpoint",
        )

    @checkpoint.on_update
    def select(event):
        if event.client is not None and event.value != "Choose a checkpoint":
            load_checkpoint(run_dir / event.value)

Opening alone does not fire ``on_update``. Replacing options keeps the selected
value while it remains available; removing it selects the first option and
fires a programmatic update (``event.client is None``). Refresh callbacks may be
synchronous or asynchronous, just like update callbacks.

Inputs
------

.. autoclass:: GuiInputHandle
   :members:

.. autoclass:: GuiCheckboxHandle
   :members:

.. autoclass:: GuiTextHandle
   :members:

.. autoclass:: GuiListHandle
   :members:

.. autoclass:: GuiNumberHandle
   :members:

.. autoclass:: GuiSliderHandle
   :members:

.. autoclass:: GuiMultiSliderHandle
   :members:

.. autoclass:: GuiDropdownHandle
   :members:

.. autoclass:: GuiButtonHandle
   :members:

.. autoclass:: GuiButtonGroupHandle
   :members:

.. autoclass:: GuiToggleGroupHandle
   :members:

.. autoclass:: GuiUploadButtonHandle
   :members:
   :exclude-members: value

.. autoclass:: UploadedFile
   :members:

.. autoclass:: GuiDownloadButtonHandle
   :members:

.. autoclass:: GuiPreviewButtonHandle
   :members:

Colors and vectors
------------------

.. autoclass:: GuiColorHandle
   :members:

.. autoclass:: GuiVectorHandle
   :members:

Containers
----------

.. autoclass:: GuiFolderHandle
   :members:

.. autoclass:: GuiFormHandle
   :members:

.. autoclass:: GuiTabGroupHandle
   :members:

.. autoclass:: GuiTabHandle
   :members:

.. autoclass:: GuiModalHandle
   :members:

Display
-------

.. autoclass:: GuiHtmlHandle
   :members:

.. autoclass:: GuiImageHandle
   :members:

.. autoclass:: GuiPlotlyHandle
   :members:

.. autoclass:: GuiProgressBarHandle
   :members:

.. autoclass:: GuiDividerHandle
   :members:

.. autoclass:: NotificationHandle
   :members:

Events and commands
-------------------

.. autoclass:: GuiEvent
   :members:

.. autoclass:: CommandHandle
   :members:

.. autoclass:: CommandEvent
   :members:

Types
-----

.. autodata:: FileContent
