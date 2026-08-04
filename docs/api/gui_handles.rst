GUI handles
===========

.. currentmodule:: leika

Handles are returned by the ``leika.GuiApi.add_*`` methods. Input handles carry
a ``value`` and support ``on_update`` callbacks; container handles can be used
as context managers to scope the controls added inside them.

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

.. autoclass:: GuiChecklistHandle
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

.. autoclass:: GuiToggleHandle
   :members:

.. autoclass:: GuiToggleGroupHandle
   :members:

.. autoclass:: GuiUploadButtonHandle
   :members:

.. autoclass:: UploadedFile
   :members:

.. autoclass:: GuiDownloadButtonHandle
   :members:

.. autoclass:: GuiPreviewButtonHandle
   :members:

Colors and vectors
------------------

.. autoclass:: GuiRgbHandle
   :members:

.. autoclass:: GuiRgbaHandle
   :members:

.. autoclass:: GuiVector2Handle
   :members:

.. autoclass:: GuiVector3Handle
   :members:

Containers
----------

.. autoclass:: GuiFolderHandle
   :members:

.. autoclass:: GuiFormHandle
   :members:

.. autoclass:: GuiTabGroupHandle
   :members:

.. data:: GuiTabGroup

   Alias for :class:`GuiTabGroupHandle`.

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

.. autodata:: DownloadContent

.. autodata:: PreviewContent
