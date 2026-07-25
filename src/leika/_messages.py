"""Message type definitions. For synchronization with the TypeScript definitions, see
`_typescript_interface_gen.py.`"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any, ClassVar, Dict, Optional, Tuple, Union, cast

import numpy as np
import numpy.typing as npt
from typing_extensions import Literal, TypeAlias, override

from . import infra, theme, uplot

KeyModifier = Literal[
    "cmd/ctrl",
    "alt",
    "shift",
    "cmd/ctrl+alt",
    "cmd/ctrl+shift",
    "alt+shift",
    "cmd/ctrl+alt+shift",
]
"""Modifier-key combination, hotkey bindings. A canonically ordered ``"+"``-separated string --
``cmd/ctrl → alt → shift``. Non-canonical orderings like
``"shift+cmd/ctrl"`` type-check-fail, though the runtime parser will
accept them (it canonicalizes internally).

``cmd/ctrl`` matches whenever either Cmd or Ctrl is held; the two
keys are deliberately collapsed (the same gesture is "Cmd" on Mac
and "Ctrl" elsewhere)."""

_KEY_MODIFIER_CANONICAL_ORDER: Tuple[str, ...] = ("cmd/ctrl", "alt", "shift")


def _normalize_key_modifier(modifier: Optional[str]) -> Optional[KeyModifier]:
    """Parse a :data:`KeyModifier` string into its canonical form.

    ``None`` and ``""`` map to ``None``. Otherwise, split on ``"+"``,
    validate each name, and canonicalize the order -- both
    ``"cmd/ctrl+shift"`` and ``"shift+cmd/ctrl"`` yield
    ``"cmd/ctrl+shift"``. Type annotations only allow the canonical
    form; the runtime is lenient for users who don't run a type-checker.
    """
    if modifier is None or modifier == "":
        return None
    parts = modifier.split("+")
    modifier_set = set(parts)
    valid = set(_KEY_MODIFIER_CANONICAL_ORDER)
    unknown = modifier_set - valid
    if unknown:
        raise ValueError(
            f"Unknown modifier(s) in {modifier!r}: {sorted(unknown)!r}. "
            f"Valid modifiers: {sorted(valid)!r}."
        )
    if len(parts) != len(modifier_set):
        duplicates = [p for p in parts if parts.count(p) > 1]
        raise ValueError(f"Duplicate modifier(s) in {modifier!r}: {sorted(set(duplicates))!r}.")
    return cast(
        KeyModifier,
        "+".join(m for m in _KEY_MODIFIER_CANONICAL_ORDER if m in modifier_set),
    )


HotkeyKey = Literal[
    # Letters.
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "Q",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "X",
    "Y",
    "Z",
    # Digits.
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    # Special keys.
    "space",
    "enter",
    "escape",
    "tab",
    "backspace",
    "delete",
    "insert",
    "home",
    "end",
    "pageup",
    "pagedown",
    "arrowup",
    "arrowdown",
    "arrowleft",
    "arrowright",
]
"""A key for hotkey bindings."""


@dataclasses.dataclass(frozen=True)
class GuiSliderMark:
    value: float
    label: Optional[str]


TagLiteral = Literal["GuiComponentMessage"]

# Entity lifecycle markers. See architecture_hardening.md for design rationale.
EntityType: TypeAlias = Literal["gui", "command", "notification", "modal", "viewport"]
"""Kinds of removable entities in the protocol."""

LifecyclePhase: TypeAlias = Literal["create", "update_dict", "update_simple", "remove"]
"""Phase of an entity message. Create and Remove share a redundancy-key
namespace (so Remove supersedes Create). There are two update flavors, both
purged when their entity is removed:

- ``update_dict``: carries an ``updates`` dict; coalesces per prop-set
  (``{entity}:{id}:update:{props}``), so independent prop changes don't clobber
  each other.
- ``update_simple``: a single-purpose update with no ``updates`` dict;
  coalesces latest-wins per message *type*
  (``{entity}:{id}:update:{ClassName}``)."""

EntityIdField: TypeAlias = Literal["uuid", "pane_id"]
"""Dataclass field carrying the entity ID."""


@dataclasses.dataclass(frozen=True)
class EntityLifecycle:
    """Class-level markers that place a Message inside an entity's lifecycle.

    Passed to ``Message.__init_subclass__`` as the ``entity=`` kwarg. Messages
    that aren't part of any entity lifecycle omit the kwarg entirely.
    """

    type: EntityType
    phase: LifecyclePhase
    id_field: EntityIdField


class Message(infra.Message):
    _tags: ClassVar[Tuple[TagLiteral, ...]] = tuple()

    @override
    def redundancy_key(self) -> str:
        """Returns a unique key for this message, used for detecting redundant
        messages.

        For entity messages, this is derived from the entity markers:
        - ``create`` / ``remove`` share ``{entity_type}:{id}:create-or-remove``
          so a Remove supersedes a pending Create (and vice versa).
        - ``update`` uses ``{entity_type}:{id}:update:{props}`` so prop-set
          updates coalesce among themselves but don't fight with create/remove.

        For non-entity messages, falls back to a name-based default that keeps
        independent messages in independent slots.
        """
        cached = self.__dict__.get("_cached_redundancy_key")
        if cached is not None:
            return cached

        if (
            self.entity_type is not None
            and self.lifecycle_phase is not None
            and self.entity_id_field is not None
        ):
            entity_id = getattr(self, self.entity_id_field)
            if self.lifecycle_phase in ("create", "remove"):
                key = f"{self.entity_type}:{entity_id}:create-or-remove"
            elif self.lifecycle_phase == "update_dict":
                # Delta updates coalesce per prop-set, so independent prop
                # changes don't clobber each other.
                updates: Dict[str, Any] = self.updates  # type: ignore[attr-defined]
                prop_suffix = ",".join(sorted(updates.keys()))
                key = f"{self.entity_type}:{entity_id}:update:{prop_suffix}"
            else:
                # update_simple: single-purpose update, coalesce latest-wins
                # per message type (so independent update message classes stay in separate slots).
                key = f"{self.entity_type}:{entity_id}:update:{type(self).__name__}"
        else:
            # Non-entity fallback: ClassName + any incidental name/uuid fields.
            parts = [type(self).__name__]
            node_name = getattr(self, "name", None)
            if node_name is not None:
                parts.append(node_name)
            uuid_val = getattr(self, "uuid", None)
            if uuid_val is not None:
                parts.append(uuid_val)
            key = "_".join(parts)

        object.__setattr__(self, "_cached_redundancy_key", key)
        return key

    def __init_subclass__(
        cls,
        tag: Optional[TagLiteral] = None,
        entity: Optional[EntityLifecycle] = None,
    ) -> None:
        """Extend class creation with:

        - ``tag=``: append to the TypeScript union tag list (existing behavior).
        - ``entity=``: declare entity lifecycle markers (type, phase, id_field)
          as a single ``EntityLifecycle`` value.
        """
        super().__init_subclass__()
        if tag is not None:
            cls._tags = cls._tags + (tag,)
        if entity is not None:
            cls.entity_type = entity.type
            cls.lifecycle_phase = entity.phase
            cls.entity_id_field = entity.id_field


@dataclasses.dataclass
class _CreateGuiComponentMessage(
    Message,
    tag="GuiComponentMessage",
    entity=EntityLifecycle("gui", "create", "uuid"),
):
    uuid: str


@dataclasses.dataclass
class GuiRemoveMessage(
    Message,
    entity=EntityLifecycle("gui", "remove", "uuid"),
):
    """Sent server->client to remove a GUI element."""

    uuid: str


@dataclasses.dataclass
class RunJavascriptMessage(Message):
    """Message for running some arbitrary Javascript on the client.
    We use this to set up the Plotly.js package, via the plotly.min.js source
    code."""

    source: str

    @override
    def redundancy_key(self) -> str:
        # Never cull these messages.
        return str(uuid.uuid4())


@dataclasses.dataclass
class NotificationShowMessage(Message, entity=EntityLifecycle("notification", "create", "uuid")):
    """Server -> client message to show a new notification."""

    uuid: str
    props: NotificationProps


@dataclasses.dataclass
class NotificationUpdateMessage(
    Message, entity=EntityLifecycle("notification", "update_simple", "uuid")
):
    """Server -> client message to update an existing notification.

    Carries the full ``NotificationProps`` so the client shares a construction
    path with ``NotificationShowMessage``."""

    uuid: str
    props: NotificationProps


@dataclasses.dataclass
class NotificationProps:
    title: str
    """Title of the notification."""
    body: str
    """Body text of the notification."""
    loading: bool
    """Whether to show a loading indicator."""
    with_close_button: bool
    """Whether to show a close button."""
    auto_close_seconds: Union[float, None]
    """Time in seconds after which the notification should auto-close, or
    False to disable auto-close."""


@dataclasses.dataclass
class RemoveNotificationMessage(Message, entity=EntityLifecycle("notification", "remove", "uuid")):
    """Remove a specific notification."""

    uuid: str


@dataclasses.dataclass
class ResetGuiMessage(Message):
    """Reset GUI."""


@dataclasses.dataclass
class GuiBaseProps:
    """Base message type containing fields commonly used by GUI inputs."""

    order: float
    """Order value for arranging GUI elements. """
    label: str
    """Label text for the GUI element."""
    hint: Optional[str]
    """Optional hint text for the GUI element."""
    visible: bool
    """Visibility state of the GUI element."""
    disabled: bool
    """Disabled state of the GUI element."""


@dataclasses.dataclass
class GuiFolderProps:
    order: float
    """Order value for arranging GUI elements. """
    label: Optional[str]
    """Label text for the GUI folder. If None, the folder is rendered without
    a header or border (useful for pure layout grouping)."""
    visible: bool
    """Visibility state of the GUI folder."""
    expand_by_default: bool
    """Whether the folder should be expanded by default."""


@dataclasses.dataclass
class GuiFolderMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiFolderProps


@dataclasses.dataclass
class GuiFormMessage(_CreateGuiComponentMessage):
    """A form is a folder whose children's values can be committed together.

    Reuses ``GuiFolderProps`` because the visual shape is identical to a
    folder; the form-specific behavior (``on_submit`` callbacks, dirty
    indicator, Cmd/Ctrl+Enter) is keyed off the message type alone."""

    container_uuid: str
    props: GuiFolderProps


@dataclasses.dataclass
class GuiFormSubmitMessage(Message):
    """Bidirectional form submit signal.

    - Sent client->server when the user presses Cmd/Ctrl+Enter inside a form.
      The server fires the form's ``on_submit`` callbacks and broadcasts this
      message to all clients.
    - Sent server->client (broadcast) after any submit (client-initiated or
      via Python ``form.submit()``). Clients clear their dirty indicator on
      receipt."""

    uuid: str


@dataclasses.dataclass
class GuiFormDirtyMessage(Message):
    """Bidirectional form dirty signal.

    - Sent client->server when any input inside the form first changes since
      the last submit. The server broadcasts this to all other clients.
    - Sent server->client (broadcast) to propagate dirty state. Clients show
      a dirty indicator on the form header on receipt."""

    uuid: str


@dataclasses.dataclass
class GuiMarkdownProps:
    order: float
    """Order value for arranging GUI elements. """
    _markdown: str
    """(Private) Markdown content to be displayed."""
    visible: bool
    """Visibility state of the markdown element."""


@dataclasses.dataclass
class GuiMarkdownMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiMarkdownProps


@dataclasses.dataclass
class GuiHtmlProps:
    order: float
    """Order value for arranging GUI elements. """
    content: str
    """HTML content to be displayed."""
    visible: bool
    """Visibility state of the markdown element."""


@dataclasses.dataclass
class GuiHtmlMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiHtmlProps


@dataclasses.dataclass
class GuiDividerProps:
    order: float
    """Order value for arranging GUI elements. """
    visible: bool
    """Visibility state of the divider."""


@dataclasses.dataclass
class GuiDividerMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiDividerProps


@dataclasses.dataclass
class GuiProgressBarProps:
    order: float
    """Order value for arranging GUI elements. """
    animated: bool
    """Whether the progress bar should be animated."""
    visible: bool
    """Visibility state of the progress bar."""


@dataclasses.dataclass
class GuiProgressBarMessage(_CreateGuiComponentMessage):
    value: float
    container_uuid: str
    props: GuiProgressBarProps


@dataclasses.dataclass
class GuiPlotlyProps:
    order: float
    """Order value for arranging GUI elements. """
    _plotly_json_str: str
    """(Private) JSON string representation of the Plotly figure."""
    aspect: float
    """Aspect ratio of the plot."""
    visible: bool
    """Visibility state of the plot."""


@dataclasses.dataclass
class GuiPlotlyMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiPlotlyProps


@dataclasses.dataclass
class GuiUplotProps:
    order: float
    """Order value for arranging GUI elements. """
    data: Tuple[npt.NDArray[np.float64], ...]
    """Tuple of 1D numpy arrays containing chart data. First array is x-axis data,
    subsequent arrays are y-axis data for each series. All arrays must have matching
    lengths. Minimum 2 arrays required."""
    mode: Union[Literal[1, 2], None]
    """Chart layout mode: 1 = aligned (all series share axes), 2 = faceted (each series
    gets its own subplot panel). Defaults to 1."""
    title: Union[str, None]
    """Chart title displayed at the top of the plot."""
    series: Tuple[uplot.Series, ...]
    """Series configuration objects defining visual appearance (colors, line styles, labels)
    and behavior for each data array. Must match data tuple length."""
    bands: Union[Tuple[uplot.Band, ...], None]
    """High/low range visualizations between adjacent series indices. Useful for confidence
    intervals, error bounds, or min/max ranges."""
    scales: Union[Dict[str, uplot.Scale], None]
    """Scale definitions controlling data-to-pixel mapping and axis ranges. Enables features
    like auto-ranging, manual bounds, time-based scaling, and logarithmic distributions.
    Multiple scales support dual-axis charts."""
    axes: Union[Tuple[uplot.Axis, ...], None]
    """Axis configuration for positioning (top/right/bottom/left), tick formatting, grid
    styling, and spacing. Controls visual appearance of chart axes."""
    legend: Union[uplot.Legend, None]
    """Legend display options including positioning, styling, and custom value formatting
    for hover states."""
    cursor: Union[uplot.Cursor, None]
    """Interactive cursor behavior including hover detection, drag-to-zoom, and crosshair
    appearance. Controls user interaction with the chart."""
    focus: Union[uplot.Focus, None]
    """Visual highlighting when hovering over series. Controls alpha transparency of
    non-focused series to emphasize the active one."""
    aspect: float
    """Width-to-height ratio for chart display (width/height). 1.0 = square, >1.0 = wider.
    Used when height is None."""
    height: Union[int, None]
    """Fixed height in pixels. Overrides aspect ratio when set."""
    padding: Union[Tuple[int, int, int, int], None]
    """Padding (top, right, bottom, left) in pixels."""
    visible: bool
    """Whether the chart is visible in the interface."""


@dataclasses.dataclass
class GuiUplotMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiUplotProps


@dataclasses.dataclass
class GuiImageProps:
    order: float
    """Order value for arranging GUI elements. """
    label: Optional[str]
    """Label text for the image."""
    _data: Optional[bytes]
    """Binary data of the image."""
    _format: Literal["jpeg", "png"]
    """Format of the provided image ('jpeg' or 'png')."""
    visible: bool
    """Visibility state of the image."""


@dataclasses.dataclass
class GuiImageMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiImageProps


@dataclasses.dataclass
class GuiTabGroupProps:
    _tab_labels: Tuple[str, ...]
    """(Private) Tuple of labels for each tab."""
    _tab_icons_html: Tuple[Union[str, None], ...]
    """(Private) Tuple of HTML strings for icons of each tab, or None if no icon."""
    _tab_container_ids: Tuple[str, ...]
    """(Private) Tuple of container IDs for each tab."""
    order: float
    """Order value for arranging GUI elements. """
    visible: bool
    """Visibility state of the tab group."""


@dataclasses.dataclass
class GuiTabGroupMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiTabGroupProps


@dataclasses.dataclass
class GuiModalMessage(
    Message,
    entity=EntityLifecycle("modal", "create", "uuid"),
):
    order: float
    uuid: str
    title: str


@dataclasses.dataclass
class GuiCloseModalMessage(
    Message,
    entity=EntityLifecycle("modal", "remove", "uuid"),
):
    uuid: str


@dataclasses.dataclass
class GuiButtonProps(GuiBaseProps):
    _icon_html: Optional[str]
    """(Private) HTML string for the icon to be displayed on the button."""
    _hold_callback_freqs: Tuple[float, ...]
    """(Private) Tuple of frequencies (Hz) at which hold callbacks should be triggered."""


@dataclasses.dataclass
class GuiButtonMessage(_CreateGuiComponentMessage):
    value: bool
    container_uuid: str
    props: GuiButtonProps


@dataclasses.dataclass
class GuiButtonHoldMessage(Message):
    """Message sent from client->server when a button is being held.

    Sent periodically at the specified frequency while the button is pressed."""

    uuid: str
    frequency: float
    """The frequency (Hz) at which this hold message was triggered."""


@dataclasses.dataclass
class GuiUploadButtonProps(GuiBaseProps):
    _icon_html: Optional[str]
    """(Private) HTML string for the icon to be displayed on the upload button."""
    mime_type: str
    """MIME type of the files that can be uploaded."""


@dataclasses.dataclass
class GuiUploadButtonMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiUploadButtonProps


@dataclasses.dataclass
class GuiSliderProps(GuiBaseProps):
    min: float
    """Minimum value for the slider."""
    max: float
    """Maximum value for the slider."""
    step: float
    """Step size for the slider."""
    precision: int
    """Number of decimal places to display for the slider value."""
    _marks: Optional[Tuple[GuiSliderMark, ...]]
    """(Private) Optional tuple of GuiSliderMark objects to display custom marks on the slider."""


@dataclasses.dataclass
class GuiSliderMessage(_CreateGuiComponentMessage):
    value: float
    container_uuid: str
    props: GuiSliderProps


@dataclasses.dataclass
class GuiMultiSliderProps(GuiBaseProps):
    min: float
    """Minimum value for the multi-slider."""
    max: float
    """Maximum value for the multi-slider."""
    step: float
    """Step size for the multi-slider."""
    min_range: Optional[float]
    """Minimum allowed range between slider handles."""
    precision: int
    """Number of decimal places to display for the multi-slider values."""
    fixed_endpoints: bool
    """If True, the first and last handles cannot be moved."""
    _marks: Optional[Tuple[GuiSliderMark, ...]]
    """(Private) Optional tuple of GuiSliderMark objects to display custom marks on the multi-slider."""


@dataclasses.dataclass
class GuiMultiSliderMessage(_CreateGuiComponentMessage):
    value: Tuple[float, ...]
    container_uuid: str
    props: GuiMultiSliderProps


@dataclasses.dataclass
class GuiNumberProps(GuiBaseProps):
    precision: int
    """Number of decimal places to display for the number value."""
    step: float
    """Step size for incrementing/decrementing the number value."""
    min: Optional[float]
    """Minimum allowed value for the number input."""
    max: Optional[float]
    """Maximum allowed value for the number input."""


@dataclasses.dataclass
class GuiNumberMessage(_CreateGuiComponentMessage):
    value: float
    container_uuid: str
    props: GuiNumberProps


@dataclasses.dataclass
class GuiRgbProps(GuiBaseProps):
    pass


@dataclasses.dataclass
class GuiRgbMessage(_CreateGuiComponentMessage):
    value: Tuple[int, int, int]
    container_uuid: str
    props: GuiRgbProps


@dataclasses.dataclass
class GuiRgbaProps(GuiBaseProps):
    pass


@dataclasses.dataclass
class GuiRgbaMessage(_CreateGuiComponentMessage):
    value: Tuple[int, int, int, int]
    container_uuid: str
    props: GuiRgbaProps


@dataclasses.dataclass
class GuiCheckboxProps(GuiBaseProps):
    pass


@dataclasses.dataclass
class GuiCheckboxMessage(_CreateGuiComponentMessage):
    value: bool
    container_uuid: str
    props: GuiCheckboxProps


@dataclasses.dataclass
class GuiVector2Props(GuiBaseProps):
    min: Optional[Tuple[float, float]]
    """Minimum allowed values for each component of the vector."""
    max: Optional[Tuple[float, float]]
    """Maximum allowed values for each component of the vector."""
    step: float
    """Step size for incrementing/decrementing each component of the vector."""
    precision: int
    """Number of decimal places to display for each component of the vector."""


@dataclasses.dataclass
class GuiVector2Message(_CreateGuiComponentMessage):
    value: Tuple[float, float]
    container_uuid: str
    props: GuiVector2Props


@dataclasses.dataclass
class GuiVector3Props(GuiBaseProps):
    min: Optional[Tuple[float, float, float]]
    """Minimum allowed values for each component of the vector."""
    max: Optional[Tuple[float, float, float]]
    """Maximum allowed values for each component of the vector."""
    step: float
    """Step size for incrementing/decrementing each component of the vector."""
    precision: int
    """Number of decimal places to display for each component of the vector."""


@dataclasses.dataclass
class GuiVector3Message(_CreateGuiComponentMessage):
    value: Tuple[float, float, float]
    container_uuid: str
    props: GuiVector3Props


@dataclasses.dataclass
class GuiTextProps(GuiBaseProps):
    multiline: bool


@dataclasses.dataclass
class GuiTextMessage(_CreateGuiComponentMessage):
    value: str
    container_uuid: str
    props: GuiTextProps


@dataclasses.dataclass
class GuiDropdownProps(GuiBaseProps):
    # This will actually be manually overridden for better types.
    options: Tuple[str, ...]
    """Tuple of options for the dropdown."""


@dataclasses.dataclass
class GuiDropdownMessage(_CreateGuiComponentMessage):
    value: str
    container_uuid: str
    props: GuiDropdownProps


@dataclasses.dataclass
class GuiButtonGroupProps(GuiBaseProps):
    options: Tuple[str, ...]
    """Tuple of buttons for the button group."""


@dataclasses.dataclass
class GuiButtonGroupMessage(_CreateGuiComponentMessage):
    value: str
    container_uuid: str
    props: GuiButtonGroupProps


@dataclasses.dataclass
class GuiUpdateMessage(
    Message,
    entity=EntityLifecycle("gui", "update_dict", "uuid"),
):
    """Sent client<->server when any property of a GUI component is changed."""

    uuid: str
    updates: Dict[str, Any]
    """Mapping from property name to new value."""


@dataclasses.dataclass
class ViewportImageProps:
    """Properties for a native image pane."""

    _data: bytes
    _format: Literal["jpeg", "png"]
    title: str
    visible: bool
    fit: Literal["contain", "cover", "fill"]


@dataclasses.dataclass
class _ViewportPaneCreateMessage(
    Message,
    entity=EntityLifecycle("viewport", "create", "pane_id"),
):
    pane_id: str
    placement: Literal["left", "right", "top", "bottom"]
    relative_to: str
    equalize_group: Tuple[str, ...]
    """Sibling pane IDs whose combined share, including this pane's, is
    redistributed equally on insertion. Empty for standalone panes."""


@dataclasses.dataclass
class ViewportImageMessage(_ViewportPaneCreateMessage):
    """Create a native image pane in the pane workspace."""

    props: ViewportImageProps


@dataclasses.dataclass
class ViewportPlotlyProps:
    """Properties for a native Plotly pane."""

    _plotly_json_str: str
    _theme_templates: str
    """JSON string with "light" and "dark" template definitions, applied by
    the client when the figure does not specify a template."""
    title: str
    visible: bool


@dataclasses.dataclass
class ViewportPlotlyMessage(_ViewportPaneCreateMessage):
    """Create a native Plotly pane in the pane workspace."""

    props: ViewportPlotlyProps


@dataclasses.dataclass
class ViewportPaneUpdateMessage(
    Message,
    entity=EntityLifecycle("viewport", "update_dict", "pane_id"),
):
    """Update one or more properties of a pane."""

    pane_id: str
    updates: Dict[str, Any]


@dataclasses.dataclass
class ViewportPaneRemoveMessage(
    Message,
    entity=EntityLifecycle("viewport", "remove", "pane_id"),
):
    """Remove a pane."""

    pane_id: str


@dataclasses.dataclass
class ViewportPaneSnapshotMessage(Message):
    """Authoritative pane IDs used to reconcile browser-persisted layouts."""

    # The hidden layout root sentinel is implicit and deliberately excluded.
    pane_ids: Tuple[str, ...]


@dataclasses.dataclass
class WorkspaceConfigurationMessage(Message):
    """Identify the workspace for browser layout persistence."""

    workspace_id: str


@dataclasses.dataclass
class ThemeConfigurationMessage(Message):
    """Message from server->client to configure parts of the GUI."""

    titlebar_content: Optional[theme.TitlebarConfig]
    control_layout: Literal["floating", "collapsible", "fixed"]
    control_width: Literal["small", "medium", "large"]
    dark_mode: bool


@dataclasses.dataclass
class FileTransferStartUpload(Message):
    """Signal that a file is about to be sent.

    This message is used to upload files from clients to the server.
    """

    source_component_uuid: str
    transfer_uuid: str
    filename: str
    mime_type: str
    part_count: int
    size_bytes: int

    @override
    def redundancy_key(self) -> str:
        return type(self).__name__ + "-" + self.transfer_uuid


@dataclasses.dataclass
class FileTransferStartDownload(Message):
    """Signal that a file is about to be sent.

    This message is used to send files to clients from the server.
    """

    save_immediately: bool
    transfer_uuid: str
    filename: str
    mime_type: str
    part_count: int
    size_bytes: int

    @override
    def redundancy_key(self) -> str:
        return type(self).__name__ + "-" + self.transfer_uuid


@dataclasses.dataclass
class FileTransferPart(Message):
    """Send a file for clients to download or upload files from client."""

    source_component_uuid: Optional[str]
    transfer_uuid: str
    part_index: int
    content: bytes

    @override
    def redundancy_key(self) -> str:
        return type(self).__name__ + "-" + self.transfer_uuid + "-" + str(self.part_index)


@dataclasses.dataclass
class FileTransferPartAck(Message):
    """Send a file for clients to download or upload files from client."""

    source_component_uuid: Optional[str]
    transfer_uuid: str
    transferred_bytes: int
    total_bytes: int

    @override
    def redundancy_key(self) -> str:
        return type(self).__name__ + "-" + self.transfer_uuid + "-" + str(self.transferred_bytes)


@dataclasses.dataclass
class SetGuiPanelLabelMessage(Message):
    """Message from server->client to set the label of the GUI panel."""

    label: Optional[str]


@dataclasses.dataclass
class CommandProps:
    """Properties for a command in the command palette."""

    label: str
    """Label displayed in the command palette."""
    description: Optional[str]
    """Description displayed below the label."""
    hotkey: Optional[HotkeyKey]
    """Hotkey key, e.g. ``"K"`` or ``"R"``."""
    modifier: Optional[KeyModifier]
    """Modifier-combo held with the hotkey, e.g. ``"cmd/ctrl"`` or
    ``"cmd/ctrl+shift"``. ``None`` matches "no modifiers held"."""
    _icon_html: Optional[str]
    """(Private) HTML string for the icon to be displayed on the command."""
    disabled: bool
    """Whether the command is disabled (visible but not triggerable)."""


@dataclasses.dataclass
class RegisterCommandMessage(
    Message,
    entity=EntityLifecycle("command", "create", "uuid"),
):
    """Message from server->client to register a command in the command palette."""

    uuid: str
    props: CommandProps


@dataclasses.dataclass
class CommandUpdateMessage(
    Message,
    entity=EntityLifecycle("command", "update_dict", "uuid"),
):
    """Message from server->client to update properties of an existing command."""

    uuid: str
    updates: Dict[str, Any]


@dataclasses.dataclass
class RemoveCommandMessage(
    Message,
    entity=EntityLifecycle("command", "remove", "uuid"),
):
    """Message from server->client to remove a command from the command palette."""

    uuid: str


@dataclasses.dataclass
class CommandTriggerMessage(Message):
    """Message from client->server when a command is triggered from the command palette."""

    uuid: str
