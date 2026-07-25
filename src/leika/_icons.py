import zipfile
from functools import lru_cache
from pathlib import Path

from ._icons_enum import IconName

ICONS_ARCHIVE = Path(__file__).resolve().parent / "_icons" / "lucide-icons.zip"


@lru_cache(maxsize=32)
def svg_from_icon(icon_name: IconName) -> str:
    """Read a Lucide icon and return it as an ``<svg />`` markup string.

    Raises:
        ValueError: If no icon with that name is bundled.
    """
    assert isinstance(icon_name, str)
    with zipfile.ZipFile(ICONS_ARCHIVE) as zip_file:
        try:
            with zip_file.open(f"{icon_name}.svg") as icon_file:
                out = icon_file.read()
        except KeyError:
            raise ValueError(
                f"Unknown icon {icon_name!r}. Names come from `leika.Icon.*`; "
                "see https://lucide.dev/icons/ for the full set."
            ) from None

    return out.decode("utf-8")
