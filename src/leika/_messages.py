"""Wire messages: the one Message base, its codec, and every message type.

The browser's TypeScript types are generated from these dataclasses; see
``_transport/_typescript.py``.
"""

from __future__ import annotations

import copy
import dataclasses
import functools
import math
from types import UnionType
from typing import Any, ClassVar, Dict, Iterator, Optional, Tuple, Union, cast

import msgspec.msgpack
import numpy as np
from typing_extensions import Literal, TypeAlias, get_args, get_origin, get_type_hints, override

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


@dataclasses.dataclass(frozen=True)
class GuiTab:
    """One tab of a tab group: its label, its icon, and the container it shows."""

    label: str
    icon_html: Optional[str]
    container_id: str


TagLiteral = Literal["GuiComponentMessage"]

# Entity lifecycle markers, which drive coalescing and garbage collection.
EntityType: TypeAlias = Literal[
    "gui", "command", "notification", "modal", "page", "viewport", "viewport-content"
]
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

EntityIdField: TypeAlias = Literal["uuid", "page_id", "pane_id"]
"""Dataclass field carrying all or part of an entity ID."""

FileDisposition: TypeAlias = Literal["save", "link", "preview", "warm", "reload"]
"""What the browser does with a file once every chunk of it has arrived.

- ``save``: hand it straight to the browser's own download machinery.
- ``link``: offer it in a notification, which can be right clicked to
  "Save as...".
- ``preview``: show it in a dialog, in whatever viewer its type calls for.
- ``warm``: show nothing -- hold it, ready, for the ``preview`` a nearby
  button's press is about to ask for.
- ``reload``: the same file again, later. Swapped into the dialog already
  showing it rather than opening one, so a preview left open follows the file
  it came from; if that dialog has since been closed, the transfer is
  dropped."""


@dataclasses.dataclass(frozen=True)
class EntityLifecycle:
    """Class-level markers that place a Message inside an entity's lifecycle.

    Passed to ``Message.__init_subclass__`` as the ``entity=`` kwarg. Messages
    that aren't part of any entity lifecycle omit the kwarg entirely.
    """

    type: EntityType
    phase: LifecyclePhase
    id_field: EntityIdField | Tuple[EntityIdField, ...]


class Message:
    """Base of every wire message. Concrete messages are dataclasses whose
    fields are the wire schema; the class name is the ``type`` discriminant."""

    excluded_self_client: Optional[int] = None
    """Client this message is not sent to: the one whose change it echoes."""

    _tags: ClassVar[Tuple[TagLiteral, ...]] = ()
    entity_type: ClassVar[Optional[EntityType]] = None
    lifecycle_phase: ClassVar[Optional[LifecyclePhase]] = None
    entity_id_field: ClassVar[EntityIdField | Tuple[EntityIdField, ...] | None] = None
    """Field, or fields for page-scoped entities, that identify the entity."""

    def __init_subclass__(
        cls,
        tag: Optional[TagLiteral] = None,
        entity: Optional[EntityLifecycle] = None,
    ) -> None:
        """Add ``tag`` to the generated TypeScript tag unions, and place the
        class in ``entity``'s lifecycle."""
        super().__init_subclass__()
        if tag is not None:
            cls._tags = cls._tags + (tag,)
        if entity is not None:
            cls.entity_type = entity.type
            cls.lifecycle_phase = entity.phase
            cls.entity_id_field = entity.id_field

    def lifecycle_entity(self) -> tuple[str, object] | None:
        """The ``(entity type, identity)`` this message creates, updates or removes."""
        fields = self.entity_id_field
        if self.entity_type is None or fields is None:
            return None
        if isinstance(fields, str):
            return self.entity_type, getattr(self, fields)
        return self.entity_type, tuple(getattr(self, field) for field in fields)

    def redundancy_key(self) -> str | None:
        """Key under which a newer queued message replaces an older one.

        Entity messages derive theirs from the lifecycle: ``create`` and
        ``remove`` share ``{entity}:{id}:create-or-remove`` so either supersedes
        the other; ``update_dict`` coalesces per set of updated properties, so
        independent property changes don't clobber each other; ``update_simple``
        coalesces per message type. Other messages are never replaced unless
        they override this.
        """
        entity = self.lifecycle_entity()
        if entity is None:
            return None
        entity_type, entity_id = entity
        entity_key = repr(entity_id) if isinstance(entity_id, tuple) else str(entity_id)
        if self.lifecycle_phase in ("create", "remove"):
            return f"{entity_type}:{entity_key}:create-or-remove"
        if self.lifecycle_phase == "update_dict":
            updates = cast(Dict[str, Any], getattr(self, "updates"))
            return f"{entity_type}:{entity_key}:update:{','.join(sorted(updates))}"
        return f"{entity_type}:{entity_key}:update:{type(self).__name__}"

    def purge_entities(self) -> tuple[tuple[str, object], ...]:
        """Entities whose queued and retained messages this one makes obsolete."""
        entity = self.lifecycle_entity()
        return (entity,) if entity is not None and self.lifecycle_phase == "remove" else ()

    def delivery_scope(self) -> str | None:
        """Retained scope, such as a page, whose subscribers alone receive this
        message; None sends it to every client."""
        return None

    def encode(self) -> bytes:
        """Check every field against its annotation and encode the message."""
        fields = _wire_fields(type(self))
        for name, annotation in fields:
            _check_outbound(getattr(self, name), annotation)
        return _ENCODER.encode(
            {"type": type(self).__name__, **{name: getattr(self, name) for name, _ in fields}}
        )


def _encode_numpy_scalar(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"unsupported protocol value: {type(value).__name__}")


_ENCODER = msgspec.msgpack.Encoder(enc_hook=_encode_numpy_scalar)


@functools.cache
def _wire_fields(cls: type) -> tuple[tuple[str, Any], ...]:
    """A dataclass's wire fields with their resolved annotations, in order."""
    hints = get_type_hints(cls)
    return tuple((field.name, hints[field.name]) for field in dataclasses.fields(cls))


def _type_error(annotation: object, value: object) -> TypeError:
    return TypeError(f"expected {annotation!r}, got {type(value).__name__}")


def _check_outbound(value: Any, annotation: Any) -> None:
    """Reject an outbound value that doesn't match its wire annotation.

    Numpy scalars stand in for Python numbers; ``Any`` values are only
    required to be encodable.
    """
    if annotation is Any:
        return
    if annotation in (type(None), bool, str, bytes):
        if type(value) is not annotation:
            raise _type_error(annotation, value)
        return
    if annotation is int or annotation is float:
        numbers = (int, np.integer) if annotation is int else (int, float, np.integer, np.floating)
        if isinstance(value, bool) or not isinstance(value, numbers):
            raise _type_error(annotation, value)
        return
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Union or origin is UnionType:
        for option in args:
            try:
                _check_outbound(value, option)
                return
            except TypeError:
                pass
        raise _type_error(annotation, value)
    if origin is Literal:
        if not any(type(value) is type(option) and value == option for option in args):
            raise _type_error(annotation, value)
        return
    if origin is tuple:
        if type(value) is not tuple:
            raise _type_error(annotation, value)
        if len(args) == 2 and args[1] is Ellipsis:
            args = (args[0],) * len(value)
        elif len(value) != len(args):
            raise TypeError(f"expected {annotation!r} with {len(args)} items, got {len(value)}")
        for item, item_annotation in zip(value, args):
            _check_outbound(item, item_annotation)
        return
    if origin is dict:
        if type(value) is not dict:
            raise _type_error(annotation, value)
        for key, item in value.items():
            _check_outbound(key, args[0])
            _check_outbound(item, args[1])
        return
    if dataclasses.is_dataclass(annotation):
        if type(value) is not annotation:
            raise _type_error(annotation, value)
        for name, field_annotation in _wire_fields(annotation):
            _check_outbound(getattr(value, name), field_annotation)
        return
    raise TypeError(f"unsupported protocol annotation: {annotation!r}")


def validated_protocol_value_copy(value: Any) -> Any:
    """A private copy of one dynamic property value the wire can carry."""
    _ENCODER.encode(value)
    return copy.deepcopy(value)


# Bounds on what one decoded browser message may contain, beyond the
# transport's 4 MiB frame limit.
_DECODED_NODE_LIMIT = 100_000
_DECODED_CONTAINER_ITEMS_LIMIT = 65_536
_DECODED_DEPTH_LIMIT = 64
_DECODED_PAYLOAD_BYTES_LIMIT = 4 * 1024 * 1024
_JAVASCRIPT_SAFE_INTEGER_MAX = (1 << 53) - 1


def _check_decoded_shape(value: object) -> None:
    """Bound decoded amplification and reject values outside JSON plus bytes."""
    nodes = 0
    payload_bytes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _DECODED_NODE_LIMIT:
            raise ValueError("decoded protocol message contains too many values")
        if depth > _DECODED_DEPTH_LIMIT:
            raise ValueError("decoded protocol message is nested too deeply")
        if item is None or type(item) is bool:
            pass
        elif type(item) is str:
            payload_bytes += len(item.encode("utf-8"))
        elif type(item) is int:
            if abs(item) > _JAVASCRIPT_SAFE_INTEGER_MAX:
                raise ValueError("protocol integers must be JavaScript-safe")
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("protocol numbers must be finite")
        elif type(item) is bytes:
            payload_bytes += len(item)
        elif type(item) is dict:
            if len(item) > _DECODED_CONTAINER_ITEMS_LIMIT:
                raise ValueError("decoded protocol mapping contains too many items")
            if any(type(key) is not str for key in item):
                raise TypeError("decoded protocol mapping keys must be strings")
            stack.extend((key, depth + 1) for key in item)
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            if len(item) > _DECODED_CONTAINER_ITEMS_LIMIT:
                raise ValueError("decoded protocol sequence contains too many items")
            stack.extend((child, depth + 1) for child in item)
        else:
            raise TypeError(f"unsupported decoded protocol value: {type(item).__name__}")
        if payload_bytes > _DECODED_PAYLOAD_BYTES_LIMIT:
            raise ValueError("decoded protocol string and binary payload is too large")


def _from_wire(value: Any, annotation: Any) -> Any:
    """Validate one decoded browser value against its annotation and rebuild it.

    Scalars are exact (a bool isn't an int), literals are restricted to their
    declared values, and nested records and containers are checked
    recursively before any handler sees them. ``Any`` stays dynamic for
    property updates, whose handlers validate each property.
    """
    if annotation is Any:
        return value
    if annotation in (type(None), bool, str, bytes):
        if type(value) is not annotation:
            raise _type_error(annotation, value)
        return value
    if annotation is int:
        if type(value) is not int:
            raise _type_error(annotation, value)
        return value
    if annotation is float:
        # One wire number type covers integral and fractional values.
        if type(value) not in (int, float):
            raise _type_error(annotation, value)
        return float(value)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Union or origin is UnionType:
        for option in args:
            try:
                return _from_wire(value, option)
            except TypeError:
                pass
        raise _type_error(annotation, value)
    if origin is Literal:
        if any(type(value) is type(option) and value == option for option in args):
            return value
        raise _type_error(annotation, value)
    if origin is tuple:
        if type(value) is not list:
            raise _type_error(annotation, value)
        if len(args) == 2 and args[1] is Ellipsis:
            args = (args[0],) * len(value)
        elif len(value) != len(args):
            raise TypeError(f"expected {annotation!r} with {len(args)} items, got {len(value)}")
        return tuple(
            _from_wire(item, item_annotation) for item, item_annotation in zip(value, args)
        )
    if origin is dict:
        if type(value) is not dict:
            raise _type_error(annotation, value)
        return {_from_wire(key, args[0]): _from_wire(item, args[1]) for key, item in value.items()}
    if dataclasses.is_dataclass(annotation):
        if type(value) is not dict:
            raise _type_error(annotation, value)
        return _record_from_wire(cast(type, annotation), value)
    raise TypeError(f"unsupported protocol annotation: {annotation!r}")


def _record_from_wire(cls: type, mapping: dict[str, Any]) -> Any:
    fields = dict(_wire_fields(cls))
    unknown = mapping.keys() - fields.keys()
    if unknown:
        raise TypeError(f"unexpected field(s) for {cls.__name__}: {sorted(unknown)!r}")
    return cls(**{key: _from_wire(item, fields[key]) for key, item in mapping.items()})


def decode_message(data: bytes) -> Message:
    """Decode and validate one message sent by a browser."""
    mapping = msgspec.msgpack.decode(data)
    _check_decoded_shape(mapping)
    if type(mapping) is not dict:
        raise TypeError("protocol message must decode to a mapping")
    name = mapping.pop("type", None)
    message_type = MESSAGE_TYPES.get(name) if type(name) is str else None
    if message_type is None:
        raise TypeError(f"unknown protocol message type: {name!r}")
    return _record_from_wire(message_type, mapping)


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
    """Remove one GUI element, its tabs, and named descendants atomically."""

    uuid: str
    removed_uuids: Tuple[str, ...] = ()
    removed_tab_uuids: Tuple[str, ...] = ()

    @override
    def purge_entities(self) -> tuple[tuple[str, object], ...]:
        return (
            ("gui", self.uuid),
            *(("gui", uuid) for uuid in self.removed_uuids),
            *(("gui", uuid) for uuid in self.removed_tab_uuids),
        )


@dataclasses.dataclass
class RunJavascriptMessage(Message):
    """Message for running some arbitrary Javascript on the client.
    We use this to set up the Plotly.js package, via the plotly.min.js source
    code."""

    source: str


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
    None to keep it up until it is closed or removed."""


@dataclasses.dataclass
class RemoveNotificationMessage(Message, entity=EntityLifecycle("notification", "remove", "uuid")):
    """Remove a specific notification."""

    uuid: str


ButtonColor = Literal["default", "inverse"]
"""The two roles a button or toggle can take."""


@dataclasses.dataclass
class GuiBaseProps:
    """Base message type containing fields commonly used by GUI inputs."""

    order: float
    """Order value for arranging GUI elements. """
    label: Optional[str]
    """Label for the element's row, or None for a self-describing control
    (e.g. a button) that fills the row on its own. Most elements require one
    at the Python API and so never send None."""
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
class GuiPopupProps:
    order: float
    """Order value for arranging GUI elements."""
    label: str
    """Label for the popup's row."""
    visible: bool
    """Visibility state of the GUI popup."""


@dataclasses.dataclass
class GuiPopupMessage(_CreateGuiComponentMessage):
    """A folder-like container whose children open in a popout."""

    container_uuid: str
    props: GuiPopupProps


@dataclasses.dataclass
class GuiFormProps:
    order: float
    """Order value for arranging GUI elements. """
    label: Optional[str]
    """Label for the form's row, or None for a row the trigger fills on its
    own -- the same rule a button follows. Ignored when ``mini``, which has no
    row of its own to label."""
    visible: bool
    """Visibility state of the GUI form."""
    mini: bool
    """Whether this form wraps a single field rather than opening a popout.
    Drawn as that field's own row with a send button on the end of it: one
    field is not worth a door, and the button is small enough to sit beside
    what it commits."""


@dataclasses.dataclass
class GuiFormMessage(_CreateGuiComponentMessage):
    """A form is a container whose children's values are committed together.

    Its own props rather than a folder's: a form is drawn as one row that
    opens a popout, so there is no header to expand and nothing for a folder's
    ``expand_by_default`` to say."""

    container_uuid: str
    props: GuiFormProps


@dataclasses.dataclass
class GuiFormSubmitMessage(Message, entity=EntityLifecycle("gui", "update_simple", "uuid")):
    """Bidirectional form submit signal.

    - Sent client->server when the user submits a form: its submit button, or
      Enter in a single-line text input inside it. The server fires the form's
      ``on_submit`` callbacks and broadcasts this message back.
    - Sent server->client after any submit, including one from Python's
      :meth:`GuiFormHandle.submit_form`. Clients close the form's popout on
      receipt -- the question has been answered, whoever answered it, so the
      one path out is the one every way of submitting takes."""

    uuid: str


@dataclasses.dataclass
class GuiHtmlProps:
    order: float
    """Order value for arranging GUI elements. """
    content: str
    """HTML content to be displayed."""
    visible: bool
    """Visibility state of the element."""


@dataclasses.dataclass
class GuiHtmlMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiHtmlProps


PlaybackAction = Literal["play", "pause", "seek", "step", "speed", "loop"]


@dataclasses.dataclass
class GuiPlaybackProps:
    order: float
    label: str | None
    visible: bool
    disabled: bool
    time: float
    """Current time in seconds, published by the application."""
    duration: float
    """Timeline extent in seconds; zero disables transport controls."""
    playing: bool
    speed: float
    loop: bool
    fps: float | None
    """Optional frame rate for frame-sized seeking and stepping."""
    buffering: bool
    """Application is preparing content; controls remain responsive."""


@dataclasses.dataclass
class GuiPlaybackMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiPlaybackProps


@dataclasses.dataclass
class GuiPlaybackCommandMessage(Message):
    uuid: str
    action: PlaybackAction
    value: float


@dataclasses.dataclass
class GuiVideoControlsProps:
    order: float
    """Order value for arranging GUI elements."""
    label: str | None
    """Optional row label. Labelled controls use the compact playback layout."""
    sync_group: str
    """Playback group controlled in each browser independently."""
    visible: bool
    """Whether these controls are visible. Hiding them does not stop playback."""


@dataclasses.dataclass
class GuiVideoControlsMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiVideoControlsProps


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
    _theme_templates: str
    """JSON string with "light" and "dark" template definitions, applied by
    the client when the figure does not specify a template."""
    aspect: float
    """Width-to-height ratio for the plot display (width/height). 1.0 = square, >1.0 =
    wider."""
    visible: bool
    """Visibility state of the plot."""


@dataclasses.dataclass
class GuiPlotlyMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiPlotlyProps


@dataclasses.dataclass
class GuiImageProps:
    order: float
    """Order value for arranging GUI elements. """
    label: Optional[str]
    """Label text for the image."""
    _data: bytes
    """(Private) Encoded image bytes, in ``_format``. Always present: an image
    element is created from the image it shows."""
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
    _tabs: Tuple[GuiTab, ...]
    """(Private) Server/client-local descriptor projection. The group create
    carries an empty tuple; flat ``GuiTabMessage`` lifecycle records declare,
    update, and remove tabs before their child components."""
    order: float
    """Order value for arranging GUI elements. """
    visible: bool
    """Visibility state of the tab group."""


@dataclasses.dataclass
class GuiTabGroupMessage(_CreateGuiComponentMessage):
    container_uuid: str
    props: GuiTabGroupProps


@dataclasses.dataclass
class GuiTabMessage(
    Message,
    entity=EntityLifecycle("gui", "create", "uuid"),
):
    """Declare one stable tab container before any of its child components."""

    uuid: str
    group_uuid: str
    label: str
    icon_html: Optional[str]


@dataclasses.dataclass
class GuiTabUpdateMessage(
    Message,
    entity=EntityLifecycle("gui", "update_simple", "uuid"),
):
    """Update presentation metadata for an already-declared tab container."""

    uuid: str
    group_uuid: str
    label: str
    icon_html: Optional[str]


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
    removed_uuids: Tuple[str, ...] = ()
    removed_tab_uuids: Tuple[str, ...] = ()

    @override
    def purge_entities(self) -> tuple[tuple[str, object], ...]:
        return (
            ("modal", self.uuid),
            *(("gui", uuid) for uuid in self.removed_uuids),
            *(("gui", uuid) for uuid in self.removed_tab_uuids),
        )


@dataclasses.dataclass
class GuiButtonProps(GuiBaseProps):
    text: str
    """Text on the button's own face. Distinct from `label`, which names the
    ROW the button sits in: a button says what it does on itself, so it is
    labelled only when it needs a caption beside it as well."""
    color: ButtonColor
    """Colorway for the button: a filled accent, or an outlined companion."""
    _icon_html: Optional[str]
    """(Private) HTML string for the icon to be displayed on the button."""
    _hold_callback_freqs: Tuple[float, ...]
    """(Private) Tuple of frequencies (Hz) at which hold callbacks should be triggered."""
    _prefetch: bool
    """(Private) Whether the press's work can be begun before the press: a
    button that shows a file asks for it when it scrolls into view
    (``GuiPreviewWarmMessage``), so the press finds the file already here."""


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
class GuiPreviewOpenMessage(Message):
    """A preview-button press with the digest of its retained document, if any."""

    uuid: str
    request_uuid: str
    cached_key: str | None


@dataclasses.dataclass
class GuiPreviewReadyMessage(Message):
    """The prepared document's identity, or confirmation of retained contents."""

    uuid: str
    request_uuid: str | None
    cache_key: str | None
    source_version: str | None
    reused: bool


@dataclasses.dataclass
class GuiPreviewWarmMessage(Message):
    """Message sent from client->server when a preview button scrolls into view.

    Asks the server to begin the transfer the button's press would start, so
    that by the time the press comes the file is already in the browser. The
    server answers with an ordinary file transfer whose disposition is
    ``warm``; a press may never come, and nothing is shown for one."""

    uuid: str


@dataclasses.dataclass
class GuiPreviewTextMessage(Message):
    """Server->client: ordered text chunks, independent of image preparation.

    Also sent while warming. A stream has one source revision and grows until
    ``done``; clients keep existing document blocks while appending new ones.
    """

    uuid: str
    filename: str
    mime_type: str
    size_bytes: int
    text: str
    stream_uuid: str
    source_version: str | None
    part_index: int
    done: bool

    @override
    def redundancy_key(self) -> str:
        return f"{type(self).__name__}:{self.stream_uuid}:{self.part_index}"


@dataclasses.dataclass
class GuiPreviewImageMessage(Message):
    """Server->client: one validated image for an existing text stream.

    Published in document order, before later images finish preparing.
    The final file transfer still owns complete, downloadable contents.
    """

    uuid: str
    stream_uuid: str
    source: str
    url: str

    @override
    def redundancy_key(self) -> str:
        return f"{type(self).__name__}:{self.stream_uuid}:{self.source}"


@dataclasses.dataclass
class GuiPreviewCancelMessage(Message):
    """Server->client: a preview button could not produce its requested file.

    Closes only a still-pending local popup for this source. The accompanying
    notification explains the failure; completed previews remain in place.
    """

    uuid: str


@dataclasses.dataclass
class GuiPreviewReloadMessage(Message):
    """Message sent from client->server when a preview's reload is pressed.

    A press, and treated as one: the file is resolved exactly the way the
    button's own press resolves it -- running the caller's function, if the
    contents are a function -- and sent back with disposition ``reload``. The
    reader asked what the file says now, and only the source knows."""

    uuid: str


@dataclasses.dataclass
class GuiPreviewWatchMessage(Message):
    """Message sent from client->server while a preview is open, to ask
    whether the file behind it has changed.

    The open dialog's side of following a file: it says what it is holding and
    the server answers only if the file on disk is no longer that. Nothing is
    sent for a preview that is still current, so a preview nobody is editing
    under costs one small message a second and no bytes.

    Watching is not a press, so it never runs a caller's function: what a
    function would return cannot be known without running it, and running one
    on a timer -- with whatever cost or side effects it carries -- is not
    something a reader leaving a dialog open has asked for. Only a file on
    disk is watched."""

    uuid: str
    version: Optional[str]
    """``source_version`` from the transfer the dialog is showing; the server
    sends the file again when the source no longer matches it."""


@dataclasses.dataclass
class GuiUploadButtonProps(GuiBaseProps):
    text: str
    """Text on the button's own face; see `GuiButtonProps.text`."""
    color: ButtonColor
    """Colorway for the button: a filled accent, or an outlined companion."""
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
    show_value: bool
    """Whether to show the editable number box beside the slider."""
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
class GuiToggleProps(GuiBaseProps):
    text: str
    """Text on the toggle's own face; see `GuiButtonProps.text`."""
    color: ButtonColor
    """Colorway for the toggle. The same two roles a button takes, and the ON
    state is that button's own pressed appearance."""
    _icon_html: Optional[str]
    """(Private) HTML string for the icon to be displayed on the toggle."""


@dataclasses.dataclass
class GuiToggleMessage(_CreateGuiComponentMessage):
    value: bool
    container_uuid: str
    props: GuiToggleProps


@dataclasses.dataclass
class GuiToggleGroupProps(GuiBaseProps):
    color: Tuple[ButtonColor, ...]
    """One colorway per toggle; see `GuiButtonGroupProps.color`."""
    options: Tuple[str, ...]
    """Tuple of toggles in the group."""
    multiple: bool
    """Whether more than one option may be on at a time. False makes the group
    a choice between its options, where turning one on turns the rest off."""
    required: bool
    """Whether one option must always be on. True refuses the press that would
    empty the row, so the value is never an empty tuple."""
    _merge: Tuple[bool, ...]
    """(Private) One flag per gap between toggles; see
    `GuiButtonGroupProps._merge`."""


@dataclasses.dataclass
class GuiToggleGroupMessage(_CreateGuiComponentMessage):
    value: Tuple[str, ...]
    """The options currently on, in the order they were declared. Holds at most
    one unless the group is `multiple`."""
    container_uuid: str
    props: GuiToggleGroupProps


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
    rows: Optional[int]
    """The box's height in lines when ``multiline`` is set: more text scrolls
    inside it. None leaves the height to the field -- three lines editable (a
    fixed height, so the panel does not reflow under typing), fitted to its
    text when read-only. Ignored by a single-line field."""
    editable: bool
    """Whether the viewer can type in it. Read-only, it is not an input at
    all, and the value changes only when Python changes it."""
    markdown: bool
    """Whether the value is drawn as markdown. Only for a read-only field: an
    editable field is editing the source, so it always shows it."""
    _source: str
    """(Private) The value with its relative image paths resolved to data URLs
    -- the browser cannot read a path on the server's disk. Kept in step with
    the value whenever a rendered field could be looking at it."""


@dataclasses.dataclass
class GuiTextMessage(_CreateGuiComponentMessage):
    value: str
    container_uuid: str
    props: GuiTextProps


@dataclasses.dataclass
class GuiListProps(GuiBaseProps):
    frozen: bool
    """Whether the list's LENGTH and ORDER are fixed. Frozen, the entries can
    still be edited but none can be added, removed, or moved, and the controls
    that would do those things are not drawn. Separate from ``disabled``, which
    stops the entries being edited as well."""


@dataclasses.dataclass
class GuiListMessage(_CreateGuiComponentMessage):
    value: Tuple[str, ...]
    container_uuid: str
    props: GuiListProps


@dataclasses.dataclass
class GuiChecklistProps(GuiBaseProps):
    frozen: bool
    """Whether the ITEMS are fixed: their words, their number, and their order.
    Frozen, a row is the words rather than a box to type them in, and what the
    viewer does with the list is tick it. Separate from ``disabled``, which
    stops the ticking too. Stronger than a list's ``frozen``, which leaves the
    typing alone, because on a checklist the answer being asked for is the
    ticks and the words are only what they are against."""


@dataclasses.dataclass
class GuiChecklistMessage(_CreateGuiComponentMessage):
    value: Tuple[Tuple[str, bool], ...]
    """One (text, checked) pair per item, in the order they are shown."""
    container_uuid: str
    props: GuiChecklistProps


@dataclasses.dataclass
class GuiRadioListProps(GuiBaseProps):
    frozen: bool
    """Whether the ITEMS are fixed: their words, their number, and their order.
    Frozen, a row is the words rather than a box to type them in, and what the
    viewer does with the list is select one. Separate from ``disabled``, which
    stops selection too."""


@dataclasses.dataclass
class GuiRadioListMessage(_CreateGuiComponentMessage):
    value: Tuple[Tuple[str, bool], ...]
    """One (text, selected) pair per item, with at most one selected."""
    container_uuid: str
    props: GuiRadioListProps


@dataclasses.dataclass
class GuiDropdownProps(GuiBaseProps):
    # This will actually be manually overridden for better types.
    options: Tuple[str, ...]
    """Tuple of options for the dropdown."""
    searchable: bool
    """Whether the open dropdown offers a search box to filter the options."""


@dataclasses.dataclass
class GuiDropdownMessage(_CreateGuiComponentMessage):
    value: str
    container_uuid: str
    props: GuiDropdownProps


@dataclasses.dataclass
class GuiButtonGroupProps(GuiBaseProps):
    color: Tuple[ButtonColor, ...]
    """One colorway per option: filled with the accent, or outlined. The same
    two roles a single button takes -- these are buttons, so none of them is
    ever the selected one -- but taken per button, so a row can put its accent
    behind one action and leave the rest quiet. Always as long as
    ``options``; the Python API fills a single role across the row."""
    options: Tuple[str, ...]
    """Tuple of buttons for the button group."""
    _merge: Tuple[bool, ...]
    """(Private) One flag per gap between buttons: True joins that pair into
    one block, False parts them. Always ``len(options) - 1`` long."""


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
class GuiRefreshMessage(Message):
    """GUI input whose dependent panes have already been hidden locally."""

    uuid: str
    updates: Dict[str, Any]
    request_id: str


@dataclasses.dataclass
class ViewportImageProps:
    """Properties for a native image pane."""

    _data: bytes
    _format: Literal["jpeg", "png"]
    title: str
    visible: bool
    loading: bool | str
    """False hides the loading overlay, True shows its default treatment, and
    a string shows that text with the loading indicator."""
    fit: Optional[Literal["fit", "fill", "stretch"]]
    """How the image is sized in its pane. None defers to the viewer's own
    "Image fit" setting, which is where an app that has no opinion leaves it."""


class _PageScopedMessage(Message):
    """Retained payload delivered only while its page is subscribed."""

    @override
    def delivery_scope(self) -> str:
        return self.page_id

    page_id: str


@dataclasses.dataclass
class _ViewportPaneCreateMessage(
    _PageScopedMessage,
    entity=EntityLifecycle("viewport-content", "create", ("page_id", "pane_id")),
):
    page_id: str
    pane_id: str
    placement: Literal["left", "right", "top", "bottom"]
    relative_to: Optional[str]
    """Pane to split beside; None, or a pane the browser no longer shows, means
    its last pane, and a pane added to an empty workspace fills it."""
    equalize_group: Tuple[str, ...]
    """Sibling pane IDs whose combined share, including this pane's, is
    redistributed equally on insertion. Empty for standalone panes."""


@dataclasses.dataclass
class ViewportEmptyProps:
    title: str
    visible: bool
    loading: bool | str


@dataclasses.dataclass
class ViewportPaneMessage(
    _ViewportPaneCreateMessage,
    entity=EntityLifecycle("viewport", "create", ("page_id", "pane_id")),
):
    """Stable placement declaration, retained in initial layout order.

    Renderer declarations have a separate lifecycle so replacing content never
    changes placement order for a newly connected browser.
    """

    props: ViewportEmptyProps


@dataclasses.dataclass
class ViewportEmptyMessage(_ViewportPaneCreateMessage):
    """Declare an empty pane, or clear an existing pane without changing its ID."""

    props: ViewportEmptyProps


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
    loading: bool | str


@dataclasses.dataclass
class ViewportMatplotlibProps:
    """Properties for a native matplotlib pane."""

    _svg: str
    """The figure serialized as SVG source, rendered as-is. Vector, so the
    pane scales it without asking Python to redraw."""
    title: str
    visible: bool
    loading: bool | str


@dataclasses.dataclass
class ViewportMatplotlibMessage(_ViewportPaneCreateMessage):
    """Create a native matplotlib pane in the pane workspace."""

    props: ViewportMatplotlibProps


@dataclasses.dataclass
class ViewportPlotlyMessage(_ViewportPaneCreateMessage):
    """Create a native Plotly pane in the pane workspace."""

    props: ViewportPlotlyProps


@dataclasses.dataclass
class ViewportVideoProps:
    """Native media URL and presentation; video bytes travel over HTTP."""

    _url: str
    autoplay: bool
    loop: bool
    muted: bool
    controls: bool
    sync_group: str | None
    fps: float | None
    title: str
    visible: bool
    loading: bool | str


@dataclasses.dataclass
class ViewportVideoMessage(_ViewportPaneCreateMessage):
    """Create a native video pane."""

    props: ViewportVideoProps


@dataclasses.dataclass
class ViewportViserProps:
    """Properties for an embedded viser pane."""

    _url: str
    """Embed URL: Leika's same-origin proxy path for a local Viser server, or
    the caller's absolute URL, rendered near-verbatim."""
    title: str
    visible: bool
    loading: bool | str


@dataclasses.dataclass
class ViewportViserMessage(_ViewportPaneCreateMessage):
    """Create an embedded viser pane in the pane workspace."""

    props: ViewportViserProps


@dataclasses.dataclass
class ViewportPaneUpdateMessage(
    _PageScopedMessage,
    entity=EntityLifecycle("viewport-content", "update_dict", ("page_id", "pane_id")),
):
    """Update one or more properties of a pane."""

    page_id: str
    pane_id: str
    updates: Dict[str, Any]


@dataclasses.dataclass
class ViewportPaneRemoveMessage(
    _PageScopedMessage,
    entity=EntityLifecycle("viewport", "remove", ("page_id", "pane_id")),
):
    """Remove a pane."""

    page_id: str
    pane_id: str

    @override
    def purge_entities(self) -> tuple[tuple[str, object], ...]:
        key = (self.page_id, self.pane_id)
        return (("viewport", key), ("viewport-content", key))


@dataclasses.dataclass
class ViewportPaneSnapshotMessage(_PageScopedMessage):
    """Authoritative pane IDs used to reconcile browser-persisted layouts."""

    page_id: str
    pane_ids: Tuple[str, ...]

    @override
    def redundancy_key(self) -> str:
        """Keep one authoritative snapshot for each independent page."""

        return f"{type(self).__name__}:{self.page_id}"


@dataclasses.dataclass
class WorkspaceConfigurationMessage(Message):
    """Identify the workspace for browser layout persistence."""

    workspace_id: str


@dataclasses.dataclass
class PageCreateMessage(
    Message,
    entity=EntityLifecycle("page", "create", "page_id"),
):
    """Declare one page before publishing any panes that belong to it."""

    page_id: str
    name: str
    is_default: bool


@dataclasses.dataclass
class PageCatalogMessage(Message):
    """Authoritative page IDs after the declarations in this stream."""

    page_ids: Tuple[str, ...]

    @override
    def redundancy_key(self) -> str:
        return type(self).__name__


@dataclasses.dataclass
class PageSubscribeMessage(Message):
    """Select the one page whose retained payload this browser receives."""

    page_id: str
    generation: int


@dataclasses.dataclass
class PageStreamBeginMessage(Message):
    """Open a generation before its retained page replay."""

    page_id: str
    generation: int


@dataclasses.dataclass
class PageStreamReadyMessage(Message):
    """Mark one page generation complete enough to render."""

    page_id: str
    generation: int


@dataclasses.dataclass
class PageUpdateMessage(
    Message,
    entity=EntityLifecycle("page", "update_simple", "page_id"),
):
    """Update a page's display name without changing its stable identity."""

    page_id: str
    name: str


@dataclasses.dataclass
class ThemeConfigurationMessage(Message):
    """Message from server->client to configure parts of the GUI."""

    control_layout: Literal["floating", "left", "right"]
    """Where the control panel starts on desktop: floating over the canvas, or
    docked to an edge. The viewer may rearrange it afterwards."""

    theme: Literal["auto", "light", "dark"]
    """Select the viewer's Theme setting, which remains editable in Settings.
    ``"auto"`` follows the browser's ``prefers-color-scheme``."""

    @override
    def redundancy_key(self) -> str:
        return type(self).__name__


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


@dataclasses.dataclass
class FileTransferStartDownload(Message):
    """Signal that a file is about to be sent.

    This message is used to send files to clients from the server.
    """

    disposition: FileDisposition
    transfer_uuid: str
    filename: str
    mime_type: str
    part_count: int
    size_bytes: int
    source_uuid: Optional[str]
    """Component this file came out of, when one did: the preview button whose
    press sent it. What lets the browser ask for the same file again --
    ``GuiPreviewReloadMessage`` and ``GuiPreviewWatchMessage`` both name it.
    A file sent by a script rather than by a press has no source to ask, and
    the dialog offers no reload."""
    source_version: Optional[str]
    """What the source was when this went out, as an opaque stamp to compare
    later; ``None`` when the source is not something that can change under the
    reader (bytes in hand, or a function that has to be run to find out)."""


@dataclasses.dataclass
class FileTransferPart(Message):
    """Send a file for clients to download or upload files from client."""

    source_component_uuid: Optional[str]
    transfer_uuid: str
    part_index: int
    content: bytes


@dataclasses.dataclass
class FileTransferAbort(Message):
    """Cancel a file transfer in either direction with a short reason."""

    transfer_uuid: str
    reason: str


@dataclasses.dataclass
class FileTransferPartAck(Message):
    """Send a file for clients to download or upload files from client."""

    source_component_uuid: Optional[str]
    transfer_uuid: str
    transferred_bytes: int
    total_bytes: int


@dataclasses.dataclass
class ClientPingMessage(Message):
    """Message from client->server asking to be answered as soon as possible.

    The client is timing the round trip, so the server's only job is to hand
    the stamp straight back."""

    sent_ms: float
    """The client's own clock when it sent this. Meaningless to the server --
    it is echoed rather than read, so the two never have to agree on a clock."""


@dataclasses.dataclass
class ServerPongMessage(Message):
    """Message from server->client answering one ping."""

    sent_ms: float
    """The stamp that arrived on the ping, returned untouched."""

    @override
    def redundancy_key(self) -> str:
        # When a peer is slower than a ping flood, only the latest pending
        # latency sample is useful; keeping every stamp would be unbounded.
        return type(self).__name__


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


def _concrete_message_types(root: type[Message]) -> Iterator[type[Message]]:
    for subclass in root.__subclasses__():
        if dataclasses.is_dataclass(subclass) and not subclass.__name__.startswith("_"):
            yield subclass
        yield from _concrete_message_types(subclass)


MESSAGE_TYPES: dict[str, type[Message]] = {
    message_type.__name__: message_type for message_type in _concrete_message_types(Message)
}
"""Every wire message type, by its ``type`` discriminant."""
