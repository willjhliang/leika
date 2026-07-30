from typing import Literal, Optional, Tuple, TypedDict, Union

from .._icons import svg_from_icon
from .._icons_enum import IconName

_GITHUB_SVG = (
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
    '<path d="M12 .5C5.73.5.5 5.73.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.56'
    " 0-.28-.01-1.02-.02-2-3.2.69-3.87-1.54-3.87-1.54-.53-1.33-1.29-1.69-1.29-1.69-1.05-.72"
    ".08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26"
    ".73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.09-.12-.29-.52-1.46"
    ".11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.79 0c2.2-1.49 3.17-1.18 3.17-1.18"
    ".63 1.59.23 2.76.12 3.05.74.8 1.19 1.83 1.19 3.09 0 4.42-2.7 5.39-5.27 5.68"
    ".42.36.79 1.07.79 2.15 0 1.55-.02 2.8-.02 3.18 0 .31.21.68.8.56A11.51 11.51 0 0 0"
    ' 23.5 12C23.5 5.73 18.27.5 12 .5Z"/></svg>'
)


class TitlebarButton(TypedDict):
    """A link-only button that appears in the Titlebar."""

    text: Optional[str]
    icon: Optional[Union[IconName, Literal["github"]]]
    """Any Lucide icon via ``leika.Icon.*``, or ``"github"`` -- the one brand
    mark Lucide dropped, whose glyph leika ships itself."""
    href: Optional[str]


class TitlebarImage(TypedDict):
    """An image that appears on the titlebar."""

    image_url_light: str
    image_url_dark: Optional[str]
    image_alt: str
    href: Optional[str]


class TitlebarConfig(TypedDict):
    """Configure the content that appears in the titlebar."""

    buttons: Optional[Tuple[TitlebarButton, ...]]
    image: Optional[TitlebarImage]


class _TitlebarButtonData(TypedDict):
    """A titlebar button as it crosses the wire: the icon already rendered to
    SVG, so the client draws it without knowing any icon names."""

    text: Optional[str]
    icon_html: Optional[str]
    href: Optional[str]


class _TitlebarConfigData(TypedDict):
    buttons: Optional[Tuple[_TitlebarButtonData, ...]]
    image: Optional[TitlebarImage]


def _resolve_titlebar_icons(config: TitlebarConfig) -> _TitlebarConfigData:
    """Render each button's icon name to the SVG the client will draw."""
    buttons = config.get("buttons")
    resolved: Optional[Tuple[_TitlebarButtonData, ...]] = None
    if buttons is not None:
        resolved = tuple(
            _TitlebarButtonData(
                text=button.get("text"),
                icon_html=(
                    None
                    if (icon := button.get("icon")) is None
                    else (_GITHUB_SVG if icon == "github" else svg_from_icon(icon))
                ),
                href=button.get("href"),
            )
            for button in buttons
        )
    return _TitlebarConfigData(buttons=resolved, image=config.get("image"))
