Icons
=====

.. currentmodule:: leika

Anywhere Leika takes an icon, it takes a name from
`Lucide <https://lucide.dev/icons/>`_. Browse and search the set there, then
reference it as an attribute of ``leika.Icon``.

Attribute names are the Lucide name uppercased with hyphens replaced by
underscores, so ``arrow-down`` on lucide.dev becomes ``leika.Icon.ARROW_DOWN``.

.. code-block:: python

   server.gui.add_button("Capture", icon=leika.Icon.CAMERA)

Two caveats when picking a name off the website:

* Leika's icons come from ``lucide-static`` 1.26.0, pinned in the browser
  client. Icons added to Lucide after that release are not available until the
  pin moves and ``_icons_generate_enum.py`` is rerun.
* Attribute access is not validated. ``leika.Icon`` resolves any name through
  ``__getattr__``, so a misspelled or unavailable icon returns the converted
  string rather than raising, and the browser renders no icon.

.. autoclass:: Icon

.. autodata:: IconName
