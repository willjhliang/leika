// AUTOMATICALLY GENERATED message interfaces, from Python dataclass definitions.
// This file should not be manually modified.
/** GuiFolderMessage(uuid: 'str', container_uuid: 'str', props: 'GuiFolderProps')
 *
 * (automatically generated)
 */
export interface GuiFolderMessage {
  type: "GuiFolderMessage";
  uuid: string;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    visible: boolean;
    expand_by_default: boolean;
  };
}
/** A folder-like container whose children open in a popout.
 *
 * (automatically generated)
 */
export interface GuiPopupMessage {
  type: "GuiPopupMessage";
  uuid: string;
  container_uuid: string;
  props: { order: number; label: string; visible: boolean };
}
/** A form is a container whose children's values are committed together.
 *
 * Its own props rather than a folder's: a form is drawn as one row that
 * opens a popout, so there is no header to expand and nothing for a folder's
 * ``expand_by_default`` to say.
 *
 * (automatically generated)
 */
export interface GuiFormMessage {
  type: "GuiFormMessage";
  uuid: string;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    visible: boolean;
    mini: boolean;
  };
}
/** GuiHtmlMessage(uuid: 'str', container_uuid: 'str', props: 'GuiHtmlProps')
 *
 * (automatically generated)
 */
export interface GuiHtmlMessage {
  type: "GuiHtmlMessage";
  uuid: string;
  container_uuid: string;
  props: { order: number; content: string; visible: boolean };
}
/** GuiPlaybackMessage(uuid: 'str', container_uuid: 'str', props: 'GuiPlaybackProps')
 *
 * (automatically generated)
 */
export interface GuiPlaybackMessage {
  type: "GuiPlaybackMessage";
  uuid: string;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    visible: boolean;
    disabled: boolean;
    time: number;
    duration: number;
    playing: boolean;
    speed: number;
    loop: boolean;
    fps: number | null;
    buffering: boolean;
  };
}
/** GuiVideoControlsMessage(uuid: 'str', container_uuid: 'str', props: 'GuiVideoControlsProps')
 *
 * (automatically generated)
 */
export interface GuiVideoControlsMessage {
  type: "GuiVideoControlsMessage";
  uuid: string;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    sync_group: string;
    visible: boolean;
  };
}
/** GuiDividerMessage(uuid: 'str', container_uuid: 'str', props: 'GuiDividerProps')
 *
 * (automatically generated)
 */
export interface GuiDividerMessage {
  type: "GuiDividerMessage";
  uuid: string;
  container_uuid: string;
  props: { order: number; visible: boolean };
}
/** GuiProgressBarMessage(uuid: 'str', value: 'float', container_uuid: 'str', props: 'GuiProgressBarProps')
 *
 * (automatically generated)
 */
export interface GuiProgressBarMessage {
  type: "GuiProgressBarMessage";
  uuid: string;
  value: number;
  container_uuid: string;
  props: { order: number; animated: boolean; visible: boolean };
}
/** GuiPlotlyMessage(uuid: 'str', container_uuid: 'str', props: 'GuiPlotlyProps')
 *
 * (automatically generated)
 */
export interface GuiPlotlyMessage {
  type: "GuiPlotlyMessage";
  uuid: string;
  container_uuid: string;
  props: {
    order: number;
    _plotly_json_str: string;
    _theme_templates: string;
    aspect: number;
    visible: boolean;
  };
}
/** GuiImageMessage(uuid: 'str', container_uuid: 'str', props: 'GuiImageProps')
 *
 * (automatically generated)
 */
export interface GuiImageMessage {
  type: "GuiImageMessage";
  uuid: string;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    _data: Uint8Array<ArrayBuffer>;
    _format: "jpeg" | "png";
    visible: boolean;
  };
}
/** GuiTabGroupMessage(uuid: 'str', container_uuid: 'str', props: 'GuiTabGroupProps')
 *
 * (automatically generated)
 */
export interface GuiTabGroupMessage {
  type: "GuiTabGroupMessage";
  uuid: string;
  container_uuid: string;
  props: {
    _tabs: { label: string; icon_html: string | null; container_id: string }[];
    order: number;
    visible: boolean;
  };
}
/** GuiButtonMessage(uuid: 'str', value: 'bool', container_uuid: 'str', props: 'GuiButtonProps')
 *
 * (automatically generated)
 */
export interface GuiButtonMessage {
  type: "GuiButtonMessage";
  uuid: string;
  value: boolean;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    text: string;
    color: "default" | "inverse";
    _icon_html: string | null;
    _hold_callback_freqs: number[];
    _prefetch: boolean;
  };
}
/** GuiUploadButtonMessage(uuid: 'str', container_uuid: 'str', props: 'GuiUploadButtonProps')
 *
 * (automatically generated)
 */
export interface GuiUploadButtonMessage {
  type: "GuiUploadButtonMessage";
  uuid: string;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    text: string;
    color: "default" | "inverse";
    _icon_html: string | null;
    mime_type: string;
  };
}
/** GuiSliderMessage(uuid: 'str', value: 'float', container_uuid: 'str', props: 'GuiSliderProps')
 *
 * (automatically generated)
 */
export interface GuiSliderMessage {
  type: "GuiSliderMessage";
  uuid: string;
  value: number;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    min: number;
    max: number;
    step: number;
    precision: number;
    show_value: boolean;
    _marks: { value: number; label: string | null }[] | null;
  };
}
/** GuiMultiSliderMessage(uuid: 'str', value: 'Tuple[float, ...]', container_uuid: 'str', props: 'GuiMultiSliderProps')
 *
 * (automatically generated)
 */
export interface GuiMultiSliderMessage {
  type: "GuiMultiSliderMessage";
  uuid: string;
  value: number[];
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    min: number;
    max: number;
    step: number;
    min_range: number | null;
    precision: number;
    fixed_endpoints: boolean;
    _marks: { value: number; label: string | null }[] | null;
  };
}
/** GuiNumberMessage(uuid: 'str', value: 'float', container_uuid: 'str', props: 'GuiNumberProps')
 *
 * (automatically generated)
 */
export interface GuiNumberMessage {
  type: "GuiNumberMessage";
  uuid: string;
  value: number;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    precision: number;
    step: number;
    min: number | null;
    max: number | null;
  };
}
/** GuiRgbMessage(uuid: 'str', value: 'Tuple[int, int, int]', container_uuid: 'str', props: 'GuiRgbProps')
 *
 * (automatically generated)
 */
export interface GuiRgbMessage {
  type: "GuiRgbMessage";
  uuid: string;
  value: [number, number, number];
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
  };
}
/** GuiRgbaMessage(uuid: 'str', value: 'Tuple[int, int, int, int]', container_uuid: 'str', props: 'GuiRgbaProps')
 *
 * (automatically generated)
 */
export interface GuiRgbaMessage {
  type: "GuiRgbaMessage";
  uuid: string;
  value: [number, number, number, number];
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
  };
}
/** GuiToggleMessage(uuid: 'str', value: 'bool', container_uuid: 'str', props: 'GuiToggleProps')
 *
 * (automatically generated)
 */
export interface GuiToggleMessage {
  type: "GuiToggleMessage";
  uuid: string;
  value: boolean;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    text: string;
    color: "default" | "inverse";
    _icon_html: string | null;
  };
}
/** GuiToggleGroupMessage(uuid: 'str', value: 'Tuple[str, ...]', container_uuid: 'str', props: 'GuiToggleGroupProps')
 *
 * (automatically generated)
 */
export interface GuiToggleGroupMessage {
  type: "GuiToggleGroupMessage";
  uuid: string;
  value: string[];
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    color: ("default" | "inverse")[];
    options: string[];
    multiple: boolean;
    required: boolean;
    _merge: boolean[];
  };
}
/** GuiCheckboxMessage(uuid: 'str', value: 'bool', container_uuid: 'str', props: 'GuiCheckboxProps')
 *
 * (automatically generated)
 */
export interface GuiCheckboxMessage {
  type: "GuiCheckboxMessage";
  uuid: string;
  value: boolean;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
  };
}
/** GuiVector2Message(uuid: 'str', value: 'Tuple[float, float]', container_uuid: 'str', props: 'GuiVector2Props')
 *
 * (automatically generated)
 */
export interface GuiVector2Message {
  type: "GuiVector2Message";
  uuid: string;
  value: [number, number];
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    min: [number, number] | null;
    max: [number, number] | null;
    step: number;
    precision: number;
  };
}
/** GuiVector3Message(uuid: 'str', value: 'Tuple[float, float, float]', container_uuid: 'str', props: 'GuiVector3Props')
 *
 * (automatically generated)
 */
export interface GuiVector3Message {
  type: "GuiVector3Message";
  uuid: string;
  value: [number, number, number];
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    min: [number, number, number] | null;
    max: [number, number, number] | null;
    step: number;
    precision: number;
  };
}
/** GuiTextMessage(uuid: 'str', value: 'str', container_uuid: 'str', props: 'GuiTextProps')
 *
 * (automatically generated)
 */
export interface GuiTextMessage {
  type: "GuiTextMessage";
  uuid: string;
  value: string;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    multiline: boolean;
    rows: number | null;
    editable: boolean;
    markdown: boolean;
    _source: string;
  };
}
/** GuiListMessage(uuid: 'str', value: 'Tuple[str, ...]', container_uuid: 'str', props: 'GuiListProps')
 *
 * (automatically generated)
 */
export interface GuiListMessage {
  type: "GuiListMessage";
  uuid: string;
  value: string[];
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    frozen: boolean;
  };
}
/** GuiChecklistMessage(uuid: 'str', value: 'Tuple[Tuple[str, bool], ...]', container_uuid: 'str', props: 'GuiChecklistProps')
 *
 * (automatically generated)
 */
export interface GuiChecklistMessage {
  type: "GuiChecklistMessage";
  uuid: string;
  value: [string, boolean][];
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    frozen: boolean;
  };
}
/** GuiRadioListMessage(uuid: 'str', value: 'Tuple[Tuple[str, bool], ...]', container_uuid: 'str', props: 'GuiRadioListProps')
 *
 * (automatically generated)
 */
export interface GuiRadioListMessage {
  type: "GuiRadioListMessage";
  uuid: string;
  value: [string, boolean][];
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    frozen: boolean;
  };
}
/** GuiDropdownMessage(uuid: 'str', value: 'str', container_uuid: 'str', props: 'GuiDropdownProps')
 *
 * (automatically generated)
 */
export interface GuiDropdownMessage {
  type: "GuiDropdownMessage";
  uuid: string;
  value: string;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    options: string[];
    searchable: boolean;
  };
}
/** GuiButtonGroupMessage(uuid: 'str', value: 'str', container_uuid: 'str', props: 'GuiButtonGroupProps')
 *
 * (automatically generated)
 */
export interface GuiButtonGroupMessage {
  type: "GuiButtonGroupMessage";
  uuid: string;
  value: string;
  container_uuid: string;
  props: {
    order: number;
    label: string | null;
    hint: string | null;
    visible: boolean;
    disabled: boolean;
    color: ("default" | "inverse")[];
    options: string[];
    _merge: boolean[];
  };
}
/** Remove one GUI element, its tabs, and named descendants atomically.
 *
 * (automatically generated)
 */
export interface GuiRemoveMessage {
  type: "GuiRemoveMessage";
  uuid: string;
  removed_uuids: string[];
  removed_tab_uuids: string[];
}
/** Message for running some arbitrary Javascript on the client.
 * We use this to set up the Plotly.js package, via the plotly.min.js source
 * code.
 *
 * (automatically generated)
 */
export interface RunJavascriptMessage {
  type: "RunJavascriptMessage";
  source: string;
}
/** Server -> client message to show a new notification.
 *
 * (automatically generated)
 */
export interface NotificationShowMessage {
  type: "NotificationShowMessage";
  uuid: string;
  props: {
    title: string;
    body: string;
    loading: boolean;
    with_close_button: boolean;
    auto_close_seconds: number | null;
  };
}
/** Server -> client message to update an existing notification.
 *
 * Carries the full ``NotificationProps`` so the client shares a construction
 * path with ``NotificationShowMessage``.
 *
 * (automatically generated)
 */
export interface NotificationUpdateMessage {
  type: "NotificationUpdateMessage";
  uuid: string;
  props: {
    title: string;
    body: string;
    loading: boolean;
    with_close_button: boolean;
    auto_close_seconds: number | null;
  };
}
/** Remove a specific notification.
 *
 * (automatically generated)
 */
export interface RemoveNotificationMessage {
  type: "RemoveNotificationMessage";
  uuid: string;
}
/** Bidirectional form submit signal.
 *
 * - Sent client->server when the user submits a form: its submit button, or
 * Enter in a single-line text input inside it. The server fires the form's
 * ``on_submit`` callbacks and broadcasts this message back.
 * - Sent server->client after any submit, including one from Python's
 * :meth:`GuiFormHandle.submit_form`. Clients close the form's popout on
 * receipt -- the question has been answered, whoever answered it, so the
 * one path out is the one every way of submitting takes.
 *
 * (automatically generated)
 */
export interface GuiFormSubmitMessage {
  type: "GuiFormSubmitMessage";
  uuid: string;
}
/** GuiPlaybackCommandMessage(uuid: 'str', action: 'PlaybackAction', value: 'float')
 *
 * (automatically generated)
 */
export interface GuiPlaybackCommandMessage {
  type: "GuiPlaybackCommandMessage";
  uuid: string;
  action: "play" | "pause" | "seek" | "step" | "speed" | "loop";
  value: number;
}
/** Declare one stable tab container before any of its child components.
 *
 * (automatically generated)
 */
export interface GuiTabMessage {
  type: "GuiTabMessage";
  uuid: string;
  group_uuid: string;
  label: string;
  icon_html: string | null;
}
/** Update presentation metadata for an already-declared tab container.
 *
 * (automatically generated)
 */
export interface GuiTabUpdateMessage {
  type: "GuiTabUpdateMessage";
  uuid: string;
  group_uuid: string;
  label: string;
  icon_html: string | null;
}
/** GuiModalMessage(order: 'float', uuid: 'str', title: 'str')
 *
 * (automatically generated)
 */
export interface GuiModalMessage {
  type: "GuiModalMessage";
  order: number;
  uuid: string;
  title: string;
}
/** GuiCloseModalMessage(uuid: 'str', removed_uuids: 'Tuple[str, ...]' = (), removed_tab_uuids: 'Tuple[str, ...]' = ())
 *
 * (automatically generated)
 */
export interface GuiCloseModalMessage {
  type: "GuiCloseModalMessage";
  uuid: string;
  removed_uuids: string[];
  removed_tab_uuids: string[];
}
/** Message sent from client->server when a button is being held.
 *
 * Sent periodically at the specified frequency while the button is pressed.
 *
 * (automatically generated)
 */
export interface GuiButtonHoldMessage {
  type: "GuiButtonHoldMessage";
  uuid: string;
  frequency: number;
}
/** A preview-button press with the digest of its retained document, if any.
 *
 * (automatically generated)
 */
export interface GuiPreviewOpenMessage {
  type: "GuiPreviewOpenMessage";
  uuid: string;
  request_uuid: string;
  cached_key: string | null;
}
/** The prepared document's identity, or confirmation of retained contents.
 *
 * (automatically generated)
 */
export interface GuiPreviewReadyMessage {
  type: "GuiPreviewReadyMessage";
  uuid: string;
  request_uuid: string | null;
  cache_key: string | null;
  source_version: string | null;
  reused: boolean;
}
/** Message sent from client->server when a preview button scrolls into view.
 *
 * Asks the server to begin the transfer the button's press would start, so
 * that by the time the press comes the file is already in the browser. The
 * server answers with an ordinary file transfer whose disposition is
 * ``warm``; a press may never come, and nothing is shown for one.
 *
 * (automatically generated)
 */
export interface GuiPreviewWarmMessage {
  type: "GuiPreviewWarmMessage";
  uuid: string;
}
/** Server->client: ordered text chunks, independent of image preparation.
 *
 * Also sent while warming. A stream has one source revision and grows until
 * ``done``; clients keep existing document blocks while appending new ones.
 *
 *
 * (automatically generated)
 */
export interface GuiPreviewTextMessage {
  type: "GuiPreviewTextMessage";
  uuid: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  text: string;
  stream_uuid: string;
  source_version: string | null;
  part_index: number;
  done: boolean;
}
/** Server->client: one validated image for an existing text stream.
 *
 * Published in document order, before later images finish preparing.
 * The final file transfer still owns complete, downloadable contents.
 *
 *
 * (automatically generated)
 */
export interface GuiPreviewImageMessage {
  type: "GuiPreviewImageMessage";
  uuid: string;
  stream_uuid: string;
  source: string;
  url: string;
}
/** Server->client: a preview button could not produce its requested file.
 *
 * Closes only a still-pending local popup for this source. The accompanying
 * notification explains the failure; completed previews remain in place.
 *
 *
 * (automatically generated)
 */
export interface GuiPreviewCancelMessage {
  type: "GuiPreviewCancelMessage";
  uuid: string;
}
/** Message sent from client->server when a preview's reload is pressed.
 *
 * A press, and treated as one: the file is resolved exactly the way the
 * button's own press resolves it -- running the caller's function, if the
 * contents are a function -- and sent back with disposition ``reload``. The
 * reader asked what the file says now, and only the source knows.
 *
 * (automatically generated)
 */
export interface GuiPreviewReloadMessage {
  type: "GuiPreviewReloadMessage";
  uuid: string;
}
/** Message sent from client->server while a preview is open, to ask
 * whether the file behind it has changed.
 *
 * The open dialog's side of following a file: it says what it is holding and
 * the server answers only if the file on disk is no longer that. Nothing is
 * sent for a preview that is still current, so a preview nobody is editing
 * under costs one small message a second and no bytes.
 *
 * Watching is not a press, so it never runs a caller's function: what a
 * function would return cannot be known without running it, and running one
 * on a timer -- with whatever cost or side effects it carries -- is not
 * something a reader leaving a dialog open has asked for. Only a file on
 * disk is watched.
 *
 * (automatically generated)
 */
export interface GuiPreviewWatchMessage {
  type: "GuiPreviewWatchMessage";
  uuid: string;
  version: string | null;
}
/** Sent client<->server when any property of a GUI component is changed.
 *
 * (automatically generated)
 */
export interface GuiUpdateMessage {
  type: "GuiUpdateMessage";
  uuid: string;
  updates: { [key: string]: any };
}
/** GUI input whose dependent panes have already been hidden locally.
 *
 * (automatically generated)
 */
export interface GuiRefreshMessage {
  type: "GuiRefreshMessage";
  uuid: string;
  updates: { [key: string]: any };
  request_id: string;
}
/** Stable placement declaration, retained in initial layout order.
 *
 * Renderer declarations have a separate lifecycle so replacing content never
 * changes placement order for a newly connected browser.
 *
 *
 * (automatically generated)
 */
export interface ViewportPaneMessage {
  type: "ViewportPaneMessage";
  page_id: string;
  pane_id: string;
  placement: "left" | "right" | "top" | "bottom";
  relative_to: string;
  equalize_group: string[];
  props: { title: string; visible: boolean; loading: boolean | string };
}
/** Declare an empty pane, or clear an existing pane without changing its ID.
 *
 * (automatically generated)
 */
export interface ViewportEmptyMessage {
  type: "ViewportEmptyMessage";
  page_id: string;
  pane_id: string;
  placement: "left" | "right" | "top" | "bottom";
  relative_to: string;
  equalize_group: string[];
  props: { title: string; visible: boolean; loading: boolean | string };
}
/** Create a native image pane in the pane workspace.
 *
 * (automatically generated)
 */
export interface ViewportImageMessage {
  type: "ViewportImageMessage";
  page_id: string;
  pane_id: string;
  placement: "left" | "right" | "top" | "bottom";
  relative_to: string;
  equalize_group: string[];
  props: {
    _data: Uint8Array<ArrayBuffer>;
    _format: "jpeg" | "png";
    title: string;
    visible: boolean;
    loading: boolean | string;
    fit: "fit" | "fill" | "stretch" | null;
  };
}
/** Create a native matplotlib pane in the pane workspace.
 *
 * (automatically generated)
 */
export interface ViewportMatplotlibMessage {
  type: "ViewportMatplotlibMessage";
  page_id: string;
  pane_id: string;
  placement: "left" | "right" | "top" | "bottom";
  relative_to: string;
  equalize_group: string[];
  props: {
    _svg: string;
    title: string;
    visible: boolean;
    loading: boolean | string;
  };
}
/** Create a native Plotly pane in the pane workspace.
 *
 * (automatically generated)
 */
export interface ViewportPlotlyMessage {
  type: "ViewportPlotlyMessage";
  page_id: string;
  pane_id: string;
  placement: "left" | "right" | "top" | "bottom";
  relative_to: string;
  equalize_group: string[];
  props: {
    _plotly_json_str: string;
    _theme_templates: string;
    title: string;
    visible: boolean;
    loading: boolean | string;
  };
}
/** Create a native video pane.
 *
 * (automatically generated)
 */
export interface ViewportVideoMessage {
  type: "ViewportVideoMessage";
  page_id: string;
  pane_id: string;
  placement: "left" | "right" | "top" | "bottom";
  relative_to: string;
  equalize_group: string[];
  props: {
    _url: string;
    autoplay: boolean;
    loop: boolean;
    muted: boolean;
    controls: boolean;
    sync_group: string | null;
    fps: number | null;
    title: string;
    visible: boolean;
    loading: boolean | string;
  };
}
/** Create an embedded viser pane in the pane workspace.
 *
 * (automatically generated)
 */
export interface ViewportViserMessage {
  type: "ViewportViserMessage";
  page_id: string;
  pane_id: string;
  placement: "left" | "right" | "top" | "bottom";
  relative_to: string;
  equalize_group: string[];
  props: {
    _url: string | null;
    _port: number | null;
    title: string;
    visible: boolean;
    loading: boolean | string;
  };
}
/** Update one or more properties of a pane.
 *
 * (automatically generated)
 */
export interface ViewportPaneUpdateMessage {
  type: "ViewportPaneUpdateMessage";
  page_id: string;
  pane_id: string;
  updates: { [key: string]: any };
}
/** Remove a pane.
 *
 * (automatically generated)
 */
export interface ViewportPaneRemoveMessage {
  type: "ViewportPaneRemoveMessage";
  page_id: string;
  pane_id: string;
}
/** Authoritative pane IDs used to reconcile browser-persisted layouts.
 *
 * (automatically generated)
 */
export interface ViewportPaneSnapshotMessage {
  type: "ViewportPaneSnapshotMessage";
  page_id: string;
  pane_ids: string[];
}
/** Identify the workspace for browser layout persistence.
 *
 * (automatically generated)
 */
export interface WorkspaceConfigurationMessage {
  type: "WorkspaceConfigurationMessage";
  workspace_id: string;
}
/** Declare one page before publishing any panes that belong to it.
 *
 * (automatically generated)
 */
export interface PageCreateMessage {
  type: "PageCreateMessage";
  page_id: string;
  name: string;
  is_default: boolean;
}
/** Authoritative page IDs after the declarations in this stream.
 *
 * (automatically generated)
 */
export interface PageCatalogMessage {
  type: "PageCatalogMessage";
  page_ids: string[];
}
/** Select the one page whose retained payload this browser receives.
 *
 * (automatically generated)
 */
export interface PageSubscribeMessage {
  type: "PageSubscribeMessage";
  page_id: string;
  generation: number;
}
/** Open a generation before its retained page replay.
 *
 * (automatically generated)
 */
export interface PageStreamBeginMessage {
  type: "PageStreamBeginMessage";
  page_id: string;
  generation: number;
}
/** Mark one page generation complete enough to render.
 *
 * (automatically generated)
 */
export interface PageStreamReadyMessage {
  type: "PageStreamReadyMessage";
  page_id: string;
  generation: number;
}
/** Update a page's display name without changing its stable identity.
 *
 * (automatically generated)
 */
export interface PageUpdateMessage {
  type: "PageUpdateMessage";
  page_id: string;
  name: string;
}
/** Message from server->client to configure parts of the GUI.
 *
 * (automatically generated)
 */
export interface ThemeConfigurationMessage {
  type: "ThemeConfigurationMessage";
  control_layout: "floating" | "left" | "right";
  theme: "auto" | "light" | "dark";
}
/** Signal that a file is about to be sent.
 *
 * This message is used to upload files from clients to the server.
 *
 *
 * (automatically generated)
 */
export interface FileTransferStartUpload {
  type: "FileTransferStartUpload";
  source_component_uuid: string;
  transfer_uuid: string;
  filename: string;
  mime_type: string;
  part_count: number;
  size_bytes: number;
}
/** Signal that a file is about to be sent.
 *
 * This message is used to send files to clients from the server.
 *
 *
 * (automatically generated)
 */
export interface FileTransferStartDownload {
  type: "FileTransferStartDownload";
  disposition: "save" | "link" | "preview" | "warm" | "reload";
  transfer_uuid: string;
  filename: string;
  mime_type: string;
  part_count: number;
  size_bytes: number;
  source_uuid: string | null;
  source_version: string | null;
}
/** Send a file for clients to download or upload files from client.
 *
 * (automatically generated)
 */
export interface FileTransferPart {
  type: "FileTransferPart";
  source_component_uuid: string | null;
  transfer_uuid: string;
  part_index: number;
  content: Uint8Array<ArrayBuffer>;
}
/** Cancel a file transfer in either direction with a short reason.
 *
 * (automatically generated)
 */
export interface FileTransferAbort {
  type: "FileTransferAbort";
  transfer_uuid: string;
  reason: string;
}
/** Send a file for clients to download or upload files from client.
 *
 * (automatically generated)
 */
export interface FileTransferPartAck {
  type: "FileTransferPartAck";
  source_component_uuid: string | null;
  transfer_uuid: string;
  transferred_bytes: number;
  total_bytes: number;
}
/** Browser pane content dimensions in physical pixels; zero when hidden.
 *
 * (automatically generated)
 */
export interface PaneViewportMessage {
  type: "PaneViewportMessage";
  page_id: string;
  pane_id: string;
  width: number;
  height: number;
}
/** Message from client->server asking to be answered as soon as possible.
 *
 * The client is timing the round trip, so the server's only job is to hand
 * the stamp straight back.
 *
 * (automatically generated)
 */
export interface ClientPingMessage {
  type: "ClientPingMessage";
  sent_ms: number;
}
/** Message from server->client answering one ping.
 *
 * (automatically generated)
 */
export interface ServerPongMessage {
  type: "ServerPongMessage";
  sent_ms: number;
}
/** Message from server->client to register a command in the command palette.
 *
 * (automatically generated)
 */
export interface RegisterCommandMessage {
  type: "RegisterCommandMessage";
  uuid: string;
  props: {
    label: string;
    description: string | null;
    hotkey:
      | "A"
      | "B"
      | "C"
      | "D"
      | "E"
      | "F"
      | "G"
      | "H"
      | "I"
      | "J"
      | "K"
      | "L"
      | "M"
      | "N"
      | "O"
      | "P"
      | "Q"
      | "R"
      | "S"
      | "T"
      | "U"
      | "V"
      | "W"
      | "X"
      | "Y"
      | "Z"
      | "0"
      | "1"
      | "2"
      | "3"
      | "4"
      | "5"
      | "6"
      | "7"
      | "8"
      | "9"
      | "space"
      | "enter"
      | "escape"
      | "tab"
      | "backspace"
      | "delete"
      | "insert"
      | "home"
      | "end"
      | "pageup"
      | "pagedown"
      | "arrowup"
      | "arrowdown"
      | "arrowleft"
      | "arrowright"
      | null;
    modifier:
      | "cmd/ctrl"
      | "alt"
      | "shift"
      | "cmd/ctrl+alt"
      | "cmd/ctrl+shift"
      | "alt+shift"
      | "cmd/ctrl+alt+shift"
      | null;
    _icon_html: string | null;
    disabled: boolean;
  };
}
/** Message from server->client to update properties of an existing command.
 *
 * (automatically generated)
 */
export interface CommandUpdateMessage {
  type: "CommandUpdateMessage";
  uuid: string;
  updates: { [key: string]: any };
}
/** Message from server->client to remove a command from the command palette.
 *
 * (automatically generated)
 */
export interface RemoveCommandMessage {
  type: "RemoveCommandMessage";
  uuid: string;
}
/** Message from client->server when a command is triggered from the command palette.
 *
 * (automatically generated)
 */
export interface CommandTriggerMessage {
  type: "CommandTriggerMessage";
  uuid: string;
}

export type Message =
  | GuiFolderMessage
  | GuiPopupMessage
  | GuiFormMessage
  | GuiHtmlMessage
  | GuiPlaybackMessage
  | GuiVideoControlsMessage
  | GuiDividerMessage
  | GuiProgressBarMessage
  | GuiPlotlyMessage
  | GuiImageMessage
  | GuiTabGroupMessage
  | GuiButtonMessage
  | GuiUploadButtonMessage
  | GuiSliderMessage
  | GuiMultiSliderMessage
  | GuiNumberMessage
  | GuiRgbMessage
  | GuiRgbaMessage
  | GuiToggleMessage
  | GuiToggleGroupMessage
  | GuiCheckboxMessage
  | GuiVector2Message
  | GuiVector3Message
  | GuiTextMessage
  | GuiListMessage
  | GuiChecklistMessage
  | GuiRadioListMessage
  | GuiDropdownMessage
  | GuiButtonGroupMessage
  | GuiRemoveMessage
  | RunJavascriptMessage
  | NotificationShowMessage
  | NotificationUpdateMessage
  | RemoveNotificationMessage
  | GuiFormSubmitMessage
  | GuiPlaybackCommandMessage
  | GuiTabMessage
  | GuiTabUpdateMessage
  | GuiModalMessage
  | GuiCloseModalMessage
  | GuiButtonHoldMessage
  | GuiPreviewOpenMessage
  | GuiPreviewReadyMessage
  | GuiPreviewWarmMessage
  | GuiPreviewTextMessage
  | GuiPreviewImageMessage
  | GuiPreviewCancelMessage
  | GuiPreviewReloadMessage
  | GuiPreviewWatchMessage
  | GuiUpdateMessage
  | GuiRefreshMessage
  | ViewportPaneMessage
  | ViewportEmptyMessage
  | ViewportImageMessage
  | ViewportMatplotlibMessage
  | ViewportPlotlyMessage
  | ViewportVideoMessage
  | ViewportViserMessage
  | ViewportPaneUpdateMessage
  | ViewportPaneRemoveMessage
  | ViewportPaneSnapshotMessage
  | WorkspaceConfigurationMessage
  | PageCreateMessage
  | PageCatalogMessage
  | PageSubscribeMessage
  | PageStreamBeginMessage
  | PageStreamReadyMessage
  | PageUpdateMessage
  | ThemeConfigurationMessage
  | FileTransferStartUpload
  | FileTransferStartDownload
  | FileTransferPart
  | FileTransferAbort
  | FileTransferPartAck
  | PaneViewportMessage
  | ClientPingMessage
  | ServerPongMessage
  | RegisterCommandMessage
  | CommandUpdateMessage
  | RemoveCommandMessage
  | CommandTriggerMessage;
export type GuiComponentMessage =
  | GuiFolderMessage
  | GuiPopupMessage
  | GuiFormMessage
  | GuiHtmlMessage
  | GuiPlaybackMessage
  | GuiVideoControlsMessage
  | GuiDividerMessage
  | GuiProgressBarMessage
  | GuiPlotlyMessage
  | GuiImageMessage
  | GuiTabGroupMessage
  | GuiButtonMessage
  | GuiUploadButtonMessage
  | GuiSliderMessage
  | GuiMultiSliderMessage
  | GuiNumberMessage
  | GuiRgbMessage
  | GuiRgbaMessage
  | GuiToggleMessage
  | GuiToggleGroupMessage
  | GuiCheckboxMessage
  | GuiVector2Message
  | GuiVector3Message
  | GuiTextMessage
  | GuiListMessage
  | GuiChecklistMessage
  | GuiRadioListMessage
  | GuiDropdownMessage
  | GuiButtonGroupMessage;
const typeSetGuiComponentMessage = new Set([
  "GuiFolderMessage",
  "GuiPopupMessage",
  "GuiFormMessage",
  "GuiHtmlMessage",
  "GuiPlaybackMessage",
  "GuiVideoControlsMessage",
  "GuiDividerMessage",
  "GuiProgressBarMessage",
  "GuiPlotlyMessage",
  "GuiImageMessage",
  "GuiTabGroupMessage",
  "GuiButtonMessage",
  "GuiUploadButtonMessage",
  "GuiSliderMessage",
  "GuiMultiSliderMessage",
  "GuiNumberMessage",
  "GuiRgbMessage",
  "GuiRgbaMessage",
  "GuiToggleMessage",
  "GuiToggleGroupMessage",
  "GuiCheckboxMessage",
  "GuiVector2Message",
  "GuiVector3Message",
  "GuiTextMessage",
  "GuiListMessage",
  "GuiChecklistMessage",
  "GuiRadioListMessage",
  "GuiDropdownMessage",
  "GuiButtonGroupMessage",
]);
export function isGuiComponentMessage(
  message: Message,
): message is GuiComponentMessage {
  return typeSetGuiComponentMessage.has(message.type);
}

/** Hash of the package version and message schema this bundle was built
 * against. Sent at connect, so a server running different code is turned
 * away with a reason instead of feeding the page fields it cannot read. */
export const LEIKA_PROTOCOL = "5e5f7e2341c1";
