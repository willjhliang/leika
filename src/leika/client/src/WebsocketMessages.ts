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
  props: { _svg: string; title: string; visible: boolean };
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
  dark_mode: boolean | "auto";
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
  | GuiFormMessage
  | GuiHtmlMessage
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
  | GuiDropdownMessage
  | GuiButtonGroupMessage
  | GuiRemoveMessage
  | RunJavascriptMessage
  | NotificationShowMessage
  | NotificationUpdateMessage
  | RemoveNotificationMessage
  | GuiFormSubmitMessage
  | GuiTabMessage
  | GuiTabUpdateMessage
  | GuiModalMessage
  | GuiCloseModalMessage
  | GuiButtonHoldMessage
  | GuiPreviewWarmMessage
  | GuiPreviewReloadMessage
  | GuiPreviewWatchMessage
  | GuiUpdateMessage
  | ViewportImageMessage
  | ViewportMatplotlibMessage
  | ViewportPlotlyMessage
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
  | ClientPingMessage
  | ServerPongMessage
  | RegisterCommandMessage
  | CommandUpdateMessage
  | RemoveCommandMessage
  | CommandTriggerMessage;
export type GuiComponentMessage =
  | GuiFolderMessage
  | GuiFormMessage
  | GuiHtmlMessage
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
  | GuiDropdownMessage
  | GuiButtonGroupMessage;
const typeSetGuiComponentMessage = new Set([
  "GuiFolderMessage",
  "GuiFormMessage",
  "GuiHtmlMessage",
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
  "GuiDropdownMessage",
  "GuiButtonGroupMessage",
]);
export function isGuiComponentMessage(
  message: Message,
): message is GuiComponentMessage {
  return typeSetGuiComponentMessage.has(message.type);
}

const PROTOCOL_VALIDATION_MAX_VALUES = 500_000;

function isProtocolRecord(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

const PROTOCOL_IDENTIFIER_MAX_CODE_UNITS = 1024;
function isProtocolIdentifier(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= PROTOCOL_IDENTIFIER_MAX_CODE_UNITS &&
    value !== "__proto__" &&
    value !== "prototype" &&
    value !== "constructor" &&
    !/[\uD800-\uDFFF]/.test(value)
  );
}

function isProtocolTypedArray(value: unknown): boolean {
  return (
    value instanceof Uint8Array ||
    value instanceof Uint16Array ||
    value instanceof Uint32Array ||
    value instanceof Int8Array ||
    value instanceof Int16Array ||
    value instanceof Int32Array ||
    value instanceof Float32Array ||
    value instanceof Float64Array
  );
}

function isProtocolValue(value: unknown): boolean {
  // The hybrid decoder has already bounded the complete graph's depth
  // and node count. This second iterative pass rejects values that Any
  // cannot safely expose without risking call-stack/argument expansion.
  const pending: unknown[] = [value];
  let visited = 0;
  while (pending.length > 0) {
    const item = pending.pop();
    visited += 1;
    if (visited > PROTOCOL_VALIDATION_MAX_VALUES) return false;
    if (item === null || typeof item === "string" || typeof item === "boolean")
      continue;
    if (typeof item === "number") {
      if (!Number.isFinite(item)) return false;
      continue;
    }
    if (isProtocolTypedArray(item)) continue;
    if (Array.isArray(item)) {
      for (let index = item.length - 1; index >= 0; index -= 1) {
        pending.push(item[index]);
      }
      continue;
    }
    if (!isProtocolRecord(item)) return false;
    for (const key in item) {
      if (Object.hasOwn(item, key)) pending.push(item[key]);
    }
  }
  return true;
}

function isProtocolArray(
  value: unknown,
  validateItem: (item: unknown) => boolean,
): value is unknown[] {
  if (!Array.isArray(value)) return false;
  for (const item of value) if (!validateItem(item)) return false;
  return true;
}

function isProtocolMapping(
  value: unknown,
  validateItem: (item: unknown) => boolean,
): value is Record<string, unknown> {
  if (!isProtocolRecord(value)) return false;
  for (const key in value) {
    if (Object.hasOwn(value, key) && !validateItem(value[key])) return false;
  }
  return true;
}

function isProtocolStruct0(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 4 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "expand_by_default") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["expand_by_default"] === "boolean"
  );
}

function isProtocolStruct1(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 4 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "mini") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["mini"] === "boolean"
  );
}

function isProtocolStruct2(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 3 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "content") &&
    Object.hasOwn(value, "visible") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    typeof value["content"] === "string" &&
    typeof value["visible"] === "boolean"
  );
}

function isProtocolStruct3(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 2 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "visible") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    typeof value["visible"] === "boolean"
  );
}

function isProtocolStruct4(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 3 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "animated") &&
    Object.hasOwn(value, "visible") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    typeof value["animated"] === "boolean" &&
    typeof value["visible"] === "boolean"
  );
}

function isProtocolStruct5(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 4 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "_plotly_json_str") &&
    Object.hasOwn(value, "aspect") &&
    Object.hasOwn(value, "visible") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    typeof value["_plotly_json_str"] === "string" &&
    typeof value["aspect"] === "number" &&
    Number.isFinite(value["aspect"]) &&
    typeof value["visible"] === "boolean"
  );
}

function isProtocolStruct6(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 5 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "_data") &&
    Object.hasOwn(value, "_format") &&
    Object.hasOwn(value, "visible") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    value["_data"] instanceof Uint8Array &&
    (value["_format"] === "jpeg" || value["_format"] === "png") &&
    typeof value["visible"] === "boolean"
  );
}

function isProtocolStruct7(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 3 &&
    Object.hasOwn(value, "_tabs") &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "visible") &&
    isProtocolArray(value["_tabs"], (item) => isProtocolStruct31(item)) &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    typeof value["visible"] === "boolean"
  );
}

function isProtocolStruct8(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 10 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "text") &&
    Object.hasOwn(value, "color") &&
    Object.hasOwn(value, "_icon_html") &&
    Object.hasOwn(value, "_hold_callback_freqs") &&
    Object.hasOwn(value, "_prefetch") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    typeof value["text"] === "string" &&
    (value["color"] === "default" || value["color"] === "inverse") &&
    (typeof value["_icon_html"] === "string" || value["_icon_html"] === null) &&
    isProtocolArray(
      value["_hold_callback_freqs"],
      (item) => typeof item === "number" && Number.isFinite(item),
    ) &&
    typeof value["_prefetch"] === "boolean"
  );
}

function isProtocolStruct9(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 9 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "text") &&
    Object.hasOwn(value, "color") &&
    Object.hasOwn(value, "_icon_html") &&
    Object.hasOwn(value, "mime_type") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    typeof value["text"] === "string" &&
    (value["color"] === "default" || value["color"] === "inverse") &&
    (typeof value["_icon_html"] === "string" || value["_icon_html"] === null) &&
    typeof value["mime_type"] === "string"
  );
}

function isProtocolStruct10(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 11 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "min") &&
    Object.hasOwn(value, "max") &&
    Object.hasOwn(value, "step") &&
    Object.hasOwn(value, "precision") &&
    Object.hasOwn(value, "show_value") &&
    Object.hasOwn(value, "_marks") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    typeof value["min"] === "number" &&
    Number.isFinite(value["min"]) &&
    typeof value["max"] === "number" &&
    Number.isFinite(value["max"]) &&
    typeof value["step"] === "number" &&
    Number.isFinite(value["step"]) &&
    Number.isSafeInteger(value["precision"]) &&
    typeof value["show_value"] === "boolean" &&
    (isProtocolArray(value["_marks"], (item) => isProtocolStruct32(item)) ||
      value["_marks"] === null)
  );
}

function isProtocolStruct11(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 12 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "min") &&
    Object.hasOwn(value, "max") &&
    Object.hasOwn(value, "step") &&
    Object.hasOwn(value, "min_range") &&
    Object.hasOwn(value, "precision") &&
    Object.hasOwn(value, "fixed_endpoints") &&
    Object.hasOwn(value, "_marks") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    typeof value["min"] === "number" &&
    Number.isFinite(value["min"]) &&
    typeof value["max"] === "number" &&
    Number.isFinite(value["max"]) &&
    typeof value["step"] === "number" &&
    Number.isFinite(value["step"]) &&
    ((typeof value["min_range"] === "number" &&
      Number.isFinite(value["min_range"])) ||
      value["min_range"] === null) &&
    Number.isSafeInteger(value["precision"]) &&
    typeof value["fixed_endpoints"] === "boolean" &&
    (isProtocolArray(value["_marks"], (item) => isProtocolStruct32(item)) ||
      value["_marks"] === null)
  );
}

function isProtocolStruct12(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 9 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "precision") &&
    Object.hasOwn(value, "step") &&
    Object.hasOwn(value, "min") &&
    Object.hasOwn(value, "max") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    Number.isSafeInteger(value["precision"]) &&
    typeof value["step"] === "number" &&
    Number.isFinite(value["step"]) &&
    ((typeof value["min"] === "number" && Number.isFinite(value["min"])) ||
      value["min"] === null) &&
    ((typeof value["max"] === "number" && Number.isFinite(value["max"])) ||
      value["max"] === null)
  );
}

function isProtocolStruct13(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 5 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean"
  );
}

function isProtocolStruct14(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 5 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean"
  );
}

function isProtocolStruct15(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 8 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "text") &&
    Object.hasOwn(value, "color") &&
    Object.hasOwn(value, "_icon_html") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    typeof value["text"] === "string" &&
    (value["color"] === "default" || value["color"] === "inverse") &&
    (typeof value["_icon_html"] === "string" || value["_icon_html"] === null)
  );
}

function isProtocolStruct16(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 10 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "color") &&
    Object.hasOwn(value, "options") &&
    Object.hasOwn(value, "multiple") &&
    Object.hasOwn(value, "required") &&
    Object.hasOwn(value, "_merge") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    isProtocolArray(
      value["color"],
      (item) => item === "default" || item === "inverse",
    ) &&
    isProtocolArray(value["options"], (item) => typeof item === "string") &&
    typeof value["multiple"] === "boolean" &&
    typeof value["required"] === "boolean" &&
    isProtocolArray(value["_merge"], (item) => typeof item === "boolean")
  );
}

function isProtocolStruct17(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 5 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean"
  );
}

function isProtocolStruct18(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 9 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "min") &&
    Object.hasOwn(value, "max") &&
    Object.hasOwn(value, "step") &&
    Object.hasOwn(value, "precision") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    ((Array.isArray(value["min"]) &&
      value["min"].length === 2 &&
      typeof value["min"][0] === "number" &&
      Number.isFinite(value["min"][0]) &&
      typeof value["min"][1] === "number" &&
      Number.isFinite(value["min"][1])) ||
      value["min"] === null) &&
    ((Array.isArray(value["max"]) &&
      value["max"].length === 2 &&
      typeof value["max"][0] === "number" &&
      Number.isFinite(value["max"][0]) &&
      typeof value["max"][1] === "number" &&
      Number.isFinite(value["max"][1])) ||
      value["max"] === null) &&
    typeof value["step"] === "number" &&
    Number.isFinite(value["step"]) &&
    Number.isSafeInteger(value["precision"])
  );
}

function isProtocolStruct19(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 9 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "min") &&
    Object.hasOwn(value, "max") &&
    Object.hasOwn(value, "step") &&
    Object.hasOwn(value, "precision") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    ((Array.isArray(value["min"]) &&
      value["min"].length === 3 &&
      typeof value["min"][0] === "number" &&
      Number.isFinite(value["min"][0]) &&
      typeof value["min"][1] === "number" &&
      Number.isFinite(value["min"][1]) &&
      typeof value["min"][2] === "number" &&
      Number.isFinite(value["min"][2])) ||
      value["min"] === null) &&
    ((Array.isArray(value["max"]) &&
      value["max"].length === 3 &&
      typeof value["max"][0] === "number" &&
      Number.isFinite(value["max"][0]) &&
      typeof value["max"][1] === "number" &&
      Number.isFinite(value["max"][1]) &&
      typeof value["max"][2] === "number" &&
      Number.isFinite(value["max"][2])) ||
      value["max"] === null) &&
    typeof value["step"] === "number" &&
    Number.isFinite(value["step"]) &&
    Number.isSafeInteger(value["precision"])
  );
}

function isProtocolStruct20(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 10 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "multiline") &&
    Object.hasOwn(value, "rows") &&
    Object.hasOwn(value, "editable") &&
    Object.hasOwn(value, "markdown") &&
    Object.hasOwn(value, "_source") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    typeof value["multiline"] === "boolean" &&
    (Number.isSafeInteger(value["rows"]) || value["rows"] === null) &&
    typeof value["editable"] === "boolean" &&
    typeof value["markdown"] === "boolean" &&
    typeof value["_source"] === "string"
  );
}

function isProtocolStruct21(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 6 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "frozen") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    typeof value["frozen"] === "boolean"
  );
}

function isProtocolStruct22(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 6 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "frozen") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    typeof value["frozen"] === "boolean"
  );
}

function isProtocolStruct23(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 7 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "options") &&
    Object.hasOwn(value, "searchable") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    isProtocolArray(value["options"], (item) => typeof item === "string") &&
    typeof value["searchable"] === "boolean"
  );
}

function isProtocolStruct24(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 8 &&
    Object.hasOwn(value, "order") &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "hint") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "disabled") &&
    Object.hasOwn(value, "color") &&
    Object.hasOwn(value, "options") &&
    Object.hasOwn(value, "_merge") &&
    typeof value["order"] === "number" &&
    Number.isFinite(value["order"]) &&
    (typeof value["label"] === "string" || value["label"] === null) &&
    (typeof value["hint"] === "string" || value["hint"] === null) &&
    typeof value["visible"] === "boolean" &&
    typeof value["disabled"] === "boolean" &&
    isProtocolArray(
      value["color"],
      (item) => item === "default" || item === "inverse",
    ) &&
    isProtocolArray(value["options"], (item) => typeof item === "string") &&
    isProtocolArray(value["_merge"], (item) => typeof item === "boolean")
  );
}

function isProtocolStruct25(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 5 &&
    Object.hasOwn(value, "title") &&
    Object.hasOwn(value, "body") &&
    Object.hasOwn(value, "loading") &&
    Object.hasOwn(value, "with_close_button") &&
    Object.hasOwn(value, "auto_close_seconds") &&
    typeof value["title"] === "string" &&
    typeof value["body"] === "string" &&
    typeof value["loading"] === "boolean" &&
    typeof value["with_close_button"] === "boolean" &&
    ((typeof value["auto_close_seconds"] === "number" &&
      Number.isFinite(value["auto_close_seconds"])) ||
      value["auto_close_seconds"] === null)
  );
}

function isProtocolStruct26(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 5 &&
    Object.hasOwn(value, "_data") &&
    Object.hasOwn(value, "_format") &&
    Object.hasOwn(value, "title") &&
    Object.hasOwn(value, "visible") &&
    Object.hasOwn(value, "fit") &&
    value["_data"] instanceof Uint8Array &&
    (value["_format"] === "jpeg" || value["_format"] === "png") &&
    typeof value["title"] === "string" &&
    typeof value["visible"] === "boolean" &&
    (value["fit"] === "fit" ||
      value["fit"] === "fill" ||
      value["fit"] === "stretch" ||
      value["fit"] === null)
  );
}

function isProtocolStruct27(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 3 &&
    Object.hasOwn(value, "_svg") &&
    Object.hasOwn(value, "title") &&
    Object.hasOwn(value, "visible") &&
    typeof value["_svg"] === "string" &&
    typeof value["title"] === "string" &&
    typeof value["visible"] === "boolean"
  );
}

function isProtocolStruct28(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 4 &&
    Object.hasOwn(value, "_plotly_json_str") &&
    Object.hasOwn(value, "_theme_templates") &&
    Object.hasOwn(value, "title") &&
    Object.hasOwn(value, "visible") &&
    typeof value["_plotly_json_str"] === "string" &&
    typeof value["_theme_templates"] === "string" &&
    typeof value["title"] === "string" &&
    typeof value["visible"] === "boolean"
  );
}

function isProtocolStruct29(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 4 &&
    Object.hasOwn(value, "_url") &&
    Object.hasOwn(value, "_port") &&
    Object.hasOwn(value, "title") &&
    Object.hasOwn(value, "visible") &&
    (typeof value["_url"] === "string" || value["_url"] === null) &&
    (Number.isSafeInteger(value["_port"]) || value["_port"] === null) &&
    typeof value["title"] === "string" &&
    typeof value["visible"] === "boolean"
  );
}

function isProtocolStruct30(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 6 &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "description") &&
    Object.hasOwn(value, "hotkey") &&
    Object.hasOwn(value, "modifier") &&
    Object.hasOwn(value, "_icon_html") &&
    Object.hasOwn(value, "disabled") &&
    typeof value["label"] === "string" &&
    (typeof value["description"] === "string" ||
      value["description"] === null) &&
    (value["hotkey"] === "A" ||
      value["hotkey"] === "B" ||
      value["hotkey"] === "C" ||
      value["hotkey"] === "D" ||
      value["hotkey"] === "E" ||
      value["hotkey"] === "F" ||
      value["hotkey"] === "G" ||
      value["hotkey"] === "H" ||
      value["hotkey"] === "I" ||
      value["hotkey"] === "J" ||
      value["hotkey"] === "K" ||
      value["hotkey"] === "L" ||
      value["hotkey"] === "M" ||
      value["hotkey"] === "N" ||
      value["hotkey"] === "O" ||
      value["hotkey"] === "P" ||
      value["hotkey"] === "Q" ||
      value["hotkey"] === "R" ||
      value["hotkey"] === "S" ||
      value["hotkey"] === "T" ||
      value["hotkey"] === "U" ||
      value["hotkey"] === "V" ||
      value["hotkey"] === "W" ||
      value["hotkey"] === "X" ||
      value["hotkey"] === "Y" ||
      value["hotkey"] === "Z" ||
      value["hotkey"] === "0" ||
      value["hotkey"] === "1" ||
      value["hotkey"] === "2" ||
      value["hotkey"] === "3" ||
      value["hotkey"] === "4" ||
      value["hotkey"] === "5" ||
      value["hotkey"] === "6" ||
      value["hotkey"] === "7" ||
      value["hotkey"] === "8" ||
      value["hotkey"] === "9" ||
      value["hotkey"] === "space" ||
      value["hotkey"] === "enter" ||
      value["hotkey"] === "escape" ||
      value["hotkey"] === "tab" ||
      value["hotkey"] === "backspace" ||
      value["hotkey"] === "delete" ||
      value["hotkey"] === "insert" ||
      value["hotkey"] === "home" ||
      value["hotkey"] === "end" ||
      value["hotkey"] === "pageup" ||
      value["hotkey"] === "pagedown" ||
      value["hotkey"] === "arrowup" ||
      value["hotkey"] === "arrowdown" ||
      value["hotkey"] === "arrowleft" ||
      value["hotkey"] === "arrowright" ||
      value["hotkey"] === null) &&
    (value["modifier"] === "cmd/ctrl" ||
      value["modifier"] === "alt" ||
      value["modifier"] === "shift" ||
      value["modifier"] === "cmd/ctrl+alt" ||
      value["modifier"] === "cmd/ctrl+shift" ||
      value["modifier"] === "alt+shift" ||
      value["modifier"] === "cmd/ctrl+alt+shift" ||
      value["modifier"] === null) &&
    (typeof value["_icon_html"] === "string" || value["_icon_html"] === null) &&
    typeof value["disabled"] === "boolean"
  );
}

function isProtocolStruct31(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 3 &&
    Object.hasOwn(value, "label") &&
    Object.hasOwn(value, "icon_html") &&
    Object.hasOwn(value, "container_id") &&
    typeof value["label"] === "string" &&
    (typeof value["icon_html"] === "string" || value["icon_html"] === null) &&
    typeof value["container_id"] === "string" &&
    (typeof value["container_id"] !== "string" ||
      isProtocolIdentifier(value["container_id"]))
  );
}

function isProtocolStruct32(value: unknown): boolean {
  return (
    isProtocolRecord(value) &&
    Object.keys(value).length === 2 &&
    Object.hasOwn(value, "value") &&
    Object.hasOwn(value, "label") &&
    typeof value["value"] === "number" &&
    Number.isFinite(value["value"]) &&
    (typeof value["label"] === "string" || value["label"] === null)
  );
}

const messageValidators = new Map<
  string,
  (message: Record<string, unknown>) => boolean
>([
  [
    "GuiFolderMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiFolderMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct0(message["props"]),
  ],
  [
    "GuiFormMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiFormMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct1(message["props"]),
  ],
  [
    "GuiHtmlMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiHtmlMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct2(message["props"]),
  ],
  [
    "GuiDividerMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiDividerMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct3(message["props"]),
  ],
  [
    "GuiProgressBarMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiProgressBarMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["value"] === "number" &&
      Number.isFinite(message["value"]) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct4(message["props"]),
  ],
  [
    "GuiPlotlyMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiPlotlyMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct5(message["props"]),
  ],
  [
    "GuiImageMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiImageMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct6(message["props"]),
  ],
  [
    "GuiTabGroupMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiTabGroupMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct7(message["props"]),
  ],
  [
    "GuiButtonMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiButtonMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["value"] === "boolean" &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct8(message["props"]),
  ],
  [
    "GuiUploadButtonMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiUploadButtonMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct9(message["props"]),
  ],
  [
    "GuiSliderMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiSliderMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["value"] === "number" &&
      Number.isFinite(message["value"]) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct10(message["props"]),
  ],
  [
    "GuiMultiSliderMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiMultiSliderMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      isProtocolArray(
        message["value"],
        (item) => typeof item === "number" && Number.isFinite(item),
      ) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct11(message["props"]),
  ],
  [
    "GuiNumberMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiNumberMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["value"] === "number" &&
      Number.isFinite(message["value"]) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct12(message["props"]),
  ],
  [
    "GuiRgbMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiRgbMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      Array.isArray(message["value"]) &&
      message["value"].length === 3 &&
      Number.isSafeInteger(message["value"][0]) &&
      Number.isSafeInteger(message["value"][1]) &&
      Number.isSafeInteger(message["value"][2]) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct13(message["props"]),
  ],
  [
    "GuiRgbaMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiRgbaMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      Array.isArray(message["value"]) &&
      message["value"].length === 4 &&
      Number.isSafeInteger(message["value"][0]) &&
      Number.isSafeInteger(message["value"][1]) &&
      Number.isSafeInteger(message["value"][2]) &&
      Number.isSafeInteger(message["value"][3]) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct14(message["props"]),
  ],
  [
    "GuiToggleMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiToggleMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["value"] === "boolean" &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct15(message["props"]),
  ],
  [
    "GuiToggleGroupMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiToggleGroupMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      isProtocolArray(message["value"], (item) => typeof item === "string") &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct16(message["props"]),
  ],
  [
    "GuiCheckboxMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiCheckboxMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["value"] === "boolean" &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct17(message["props"]),
  ],
  [
    "GuiVector2Message",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiVector2Message" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      Array.isArray(message["value"]) &&
      message["value"].length === 2 &&
      typeof message["value"][0] === "number" &&
      Number.isFinite(message["value"][0]) &&
      typeof message["value"][1] === "number" &&
      Number.isFinite(message["value"][1]) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct18(message["props"]),
  ],
  [
    "GuiVector3Message",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiVector3Message" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      Array.isArray(message["value"]) &&
      message["value"].length === 3 &&
      typeof message["value"][0] === "number" &&
      Number.isFinite(message["value"][0]) &&
      typeof message["value"][1] === "number" &&
      Number.isFinite(message["value"][1]) &&
      typeof message["value"][2] === "number" &&
      Number.isFinite(message["value"][2]) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct19(message["props"]),
  ],
  [
    "GuiTextMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiTextMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["value"] === "string" &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct20(message["props"]),
  ],
  [
    "GuiListMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiListMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      isProtocolArray(message["value"], (item) => typeof item === "string") &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct21(message["props"]),
  ],
  [
    "GuiChecklistMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiChecklistMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      isProtocolArray(
        message["value"],
        (item) =>
          Array.isArray(item) &&
          item.length === 2 &&
          typeof item[0] === "string" &&
          typeof item[1] === "boolean",
      ) &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct22(message["props"]),
  ],
  [
    "GuiDropdownMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiDropdownMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["value"] === "string" &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct23(message["props"]),
  ],
  [
    "GuiButtonGroupMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "value") &&
      Object.hasOwn(message, "container_uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "GuiButtonGroupMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["value"] === "string" &&
      typeof message["container_uuid"] === "string" &&
      (typeof message["container_uuid"] !== "string" ||
        isProtocolIdentifier(message["container_uuid"])) &&
      isProtocolStruct24(message["props"]),
  ],
  [
    "GuiRemoveMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "removed_uuids") &&
      Object.hasOwn(message, "removed_tab_uuids") &&
      message["type"] === "GuiRemoveMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      isProtocolArray(
        message["removed_uuids"],
        (item) => typeof item === "string",
      ) &&
      isProtocolArray(
        message["removed_tab_uuids"],
        (item) => typeof item === "string",
      ),
  ],
  [
    "RunJavascriptMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 2 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "source") &&
      message["type"] === "RunJavascriptMessage" &&
      typeof message["source"] === "string",
  ],
  [
    "NotificationShowMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "NotificationShowMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      isProtocolStruct25(message["props"]),
  ],
  [
    "NotificationUpdateMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "NotificationUpdateMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      isProtocolStruct25(message["props"]),
  ],
  [
    "RemoveNotificationMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 2 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      message["type"] === "RemoveNotificationMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])),
  ],
  [
    "GuiFormSubmitMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 2 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      message["type"] === "GuiFormSubmitMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])),
  ],
  [
    "GuiTabMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "group_uuid") &&
      Object.hasOwn(message, "label") &&
      Object.hasOwn(message, "icon_html") &&
      message["type"] === "GuiTabMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["group_uuid"] === "string" &&
      typeof message["label"] === "string" &&
      (typeof message["icon_html"] === "string" ||
        message["icon_html"] === null),
  ],
  [
    "GuiTabUpdateMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "group_uuid") &&
      Object.hasOwn(message, "label") &&
      Object.hasOwn(message, "icon_html") &&
      message["type"] === "GuiTabUpdateMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["group_uuid"] === "string" &&
      typeof message["label"] === "string" &&
      (typeof message["icon_html"] === "string" ||
        message["icon_html"] === null),
  ],
  [
    "GuiModalMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "order") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "title") &&
      message["type"] === "GuiModalMessage" &&
      typeof message["order"] === "number" &&
      Number.isFinite(message["order"]) &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["title"] === "string",
  ],
  [
    "GuiCloseModalMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "removed_uuids") &&
      Object.hasOwn(message, "removed_tab_uuids") &&
      message["type"] === "GuiCloseModalMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      isProtocolArray(
        message["removed_uuids"],
        (item) => typeof item === "string",
      ) &&
      isProtocolArray(
        message["removed_tab_uuids"],
        (item) => typeof item === "string",
      ),
  ],
  [
    "GuiButtonHoldMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "frequency") &&
      message["type"] === "GuiButtonHoldMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      typeof message["frequency"] === "number" &&
      Number.isFinite(message["frequency"]),
  ],
  [
    "GuiPreviewWarmMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 2 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      message["type"] === "GuiPreviewWarmMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])),
  ],
  [
    "GuiPreviewReloadMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 2 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      message["type"] === "GuiPreviewReloadMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])),
  ],
  [
    "GuiPreviewWatchMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "version") &&
      message["type"] === "GuiPreviewWatchMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      (typeof message["version"] === "string" || message["version"] === null),
  ],
  [
    "GuiUpdateMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "updates") &&
      message["type"] === "GuiUpdateMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      isProtocolMapping(message["updates"], (item) => isProtocolValue(item)),
  ],
  [
    "ViewportImageMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 7 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "pane_id") &&
      Object.hasOwn(message, "placement") &&
      Object.hasOwn(message, "relative_to") &&
      Object.hasOwn(message, "equalize_group") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "ViewportImageMessage" &&
      typeof message["page_id"] === "string" &&
      typeof message["pane_id"] === "string" &&
      (typeof message["pane_id"] !== "string" ||
        isProtocolIdentifier(message["pane_id"])) &&
      (message["placement"] === "left" ||
        message["placement"] === "right" ||
        message["placement"] === "top" ||
        message["placement"] === "bottom") &&
      typeof message["relative_to"] === "string" &&
      (typeof message["relative_to"] !== "string" ||
        isProtocolIdentifier(message["relative_to"])) &&
      isProtocolArray(
        message["equalize_group"],
        (item) => typeof item === "string",
      ) &&
      (!Array.isArray(message["equalize_group"]) ||
        message["equalize_group"].every(isProtocolIdentifier)) &&
      isProtocolStruct26(message["props"]),
  ],
  [
    "ViewportMatplotlibMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 7 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "pane_id") &&
      Object.hasOwn(message, "placement") &&
      Object.hasOwn(message, "relative_to") &&
      Object.hasOwn(message, "equalize_group") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "ViewportMatplotlibMessage" &&
      typeof message["page_id"] === "string" &&
      typeof message["pane_id"] === "string" &&
      (typeof message["pane_id"] !== "string" ||
        isProtocolIdentifier(message["pane_id"])) &&
      (message["placement"] === "left" ||
        message["placement"] === "right" ||
        message["placement"] === "top" ||
        message["placement"] === "bottom") &&
      typeof message["relative_to"] === "string" &&
      (typeof message["relative_to"] !== "string" ||
        isProtocolIdentifier(message["relative_to"])) &&
      isProtocolArray(
        message["equalize_group"],
        (item) => typeof item === "string",
      ) &&
      (!Array.isArray(message["equalize_group"]) ||
        message["equalize_group"].every(isProtocolIdentifier)) &&
      isProtocolStruct27(message["props"]),
  ],
  [
    "ViewportPlotlyMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 7 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "pane_id") &&
      Object.hasOwn(message, "placement") &&
      Object.hasOwn(message, "relative_to") &&
      Object.hasOwn(message, "equalize_group") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "ViewportPlotlyMessage" &&
      typeof message["page_id"] === "string" &&
      typeof message["pane_id"] === "string" &&
      (typeof message["pane_id"] !== "string" ||
        isProtocolIdentifier(message["pane_id"])) &&
      (message["placement"] === "left" ||
        message["placement"] === "right" ||
        message["placement"] === "top" ||
        message["placement"] === "bottom") &&
      typeof message["relative_to"] === "string" &&
      (typeof message["relative_to"] !== "string" ||
        isProtocolIdentifier(message["relative_to"])) &&
      isProtocolArray(
        message["equalize_group"],
        (item) => typeof item === "string",
      ) &&
      (!Array.isArray(message["equalize_group"]) ||
        message["equalize_group"].every(isProtocolIdentifier)) &&
      isProtocolStruct28(message["props"]),
  ],
  [
    "ViewportViserMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 7 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "pane_id") &&
      Object.hasOwn(message, "placement") &&
      Object.hasOwn(message, "relative_to") &&
      Object.hasOwn(message, "equalize_group") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "ViewportViserMessage" &&
      typeof message["page_id"] === "string" &&
      typeof message["pane_id"] === "string" &&
      (typeof message["pane_id"] !== "string" ||
        isProtocolIdentifier(message["pane_id"])) &&
      (message["placement"] === "left" ||
        message["placement"] === "right" ||
        message["placement"] === "top" ||
        message["placement"] === "bottom") &&
      typeof message["relative_to"] === "string" &&
      (typeof message["relative_to"] !== "string" ||
        isProtocolIdentifier(message["relative_to"])) &&
      isProtocolArray(
        message["equalize_group"],
        (item) => typeof item === "string",
      ) &&
      (!Array.isArray(message["equalize_group"]) ||
        message["equalize_group"].every(isProtocolIdentifier)) &&
      isProtocolStruct29(message["props"]),
  ],
  [
    "ViewportPaneUpdateMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "pane_id") &&
      Object.hasOwn(message, "updates") &&
      message["type"] === "ViewportPaneUpdateMessage" &&
      typeof message["page_id"] === "string" &&
      typeof message["pane_id"] === "string" &&
      (typeof message["pane_id"] !== "string" ||
        isProtocolIdentifier(message["pane_id"])) &&
      isProtocolMapping(message["updates"], (item) => isProtocolValue(item)),
  ],
  [
    "ViewportPaneRemoveMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "pane_id") &&
      message["type"] === "ViewportPaneRemoveMessage" &&
      typeof message["page_id"] === "string" &&
      typeof message["pane_id"] === "string" &&
      (typeof message["pane_id"] !== "string" ||
        isProtocolIdentifier(message["pane_id"])),
  ],
  [
    "ViewportPaneSnapshotMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "pane_ids") &&
      message["type"] === "ViewportPaneSnapshotMessage" &&
      typeof message["page_id"] === "string" &&
      isProtocolArray(
        message["pane_ids"],
        (item) => typeof item === "string",
      ) &&
      (!Array.isArray(message["pane_ids"]) ||
        message["pane_ids"].every(isProtocolIdentifier)),
  ],
  [
    "WorkspaceConfigurationMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 2 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "workspace_id") &&
      message["type"] === "WorkspaceConfigurationMessage" &&
      typeof message["workspace_id"] === "string" &&
      (typeof message["workspace_id"] !== "string" ||
        isProtocolIdentifier(message["workspace_id"])),
  ],
  [
    "PageCreateMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 4 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "name") &&
      Object.hasOwn(message, "is_default") &&
      message["type"] === "PageCreateMessage" &&
      typeof message["page_id"] === "string" &&
      typeof message["name"] === "string" &&
      typeof message["is_default"] === "boolean",
  ],
  [
    "PageCatalogMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 2 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_ids") &&
      message["type"] === "PageCatalogMessage" &&
      isProtocolArray(message["page_ids"], (item) => typeof item === "string"),
  ],
  [
    "PageSubscribeMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "generation") &&
      message["type"] === "PageSubscribeMessage" &&
      typeof message["page_id"] === "string" &&
      Number.isSafeInteger(message["generation"]),
  ],
  [
    "PageStreamBeginMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "generation") &&
      message["type"] === "PageStreamBeginMessage" &&
      typeof message["page_id"] === "string" &&
      Number.isSafeInteger(message["generation"]),
  ],
  [
    "PageStreamReadyMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "generation") &&
      message["type"] === "PageStreamReadyMessage" &&
      typeof message["page_id"] === "string" &&
      Number.isSafeInteger(message["generation"]),
  ],
  [
    "PageUpdateMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "page_id") &&
      Object.hasOwn(message, "name") &&
      message["type"] === "PageUpdateMessage" &&
      typeof message["page_id"] === "string" &&
      typeof message["name"] === "string",
  ],
  [
    "ThemeConfigurationMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "control_layout") &&
      Object.hasOwn(message, "dark_mode") &&
      message["type"] === "ThemeConfigurationMessage" &&
      (message["control_layout"] === "floating" ||
        message["control_layout"] === "left" ||
        message["control_layout"] === "right") &&
      (typeof message["dark_mode"] === "boolean" ||
        message["dark_mode"] === "auto"),
  ],
  [
    "FileTransferStartUpload",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 7 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "source_component_uuid") &&
      Object.hasOwn(message, "transfer_uuid") &&
      Object.hasOwn(message, "filename") &&
      Object.hasOwn(message, "mime_type") &&
      Object.hasOwn(message, "part_count") &&
      Object.hasOwn(message, "size_bytes") &&
      message["type"] === "FileTransferStartUpload" &&
      typeof message["source_component_uuid"] === "string" &&
      (typeof message["source_component_uuid"] !== "string" ||
        isProtocolIdentifier(message["source_component_uuid"])) &&
      typeof message["transfer_uuid"] === "string" &&
      (typeof message["transfer_uuid"] !== "string" ||
        isProtocolIdentifier(message["transfer_uuid"])) &&
      typeof message["filename"] === "string" &&
      typeof message["mime_type"] === "string" &&
      Number.isSafeInteger(message["part_count"]) &&
      Number.isSafeInteger(message["size_bytes"]),
  ],
  [
    "FileTransferStartDownload",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 9 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "disposition") &&
      Object.hasOwn(message, "transfer_uuid") &&
      Object.hasOwn(message, "filename") &&
      Object.hasOwn(message, "mime_type") &&
      Object.hasOwn(message, "part_count") &&
      Object.hasOwn(message, "size_bytes") &&
      Object.hasOwn(message, "source_uuid") &&
      Object.hasOwn(message, "source_version") &&
      message["type"] === "FileTransferStartDownload" &&
      (message["disposition"] === "save" ||
        message["disposition"] === "link" ||
        message["disposition"] === "preview" ||
        message["disposition"] === "warm" ||
        message["disposition"] === "reload") &&
      typeof message["transfer_uuid"] === "string" &&
      (typeof message["transfer_uuid"] !== "string" ||
        isProtocolIdentifier(message["transfer_uuid"])) &&
      typeof message["filename"] === "string" &&
      typeof message["mime_type"] === "string" &&
      Number.isSafeInteger(message["part_count"]) &&
      Number.isSafeInteger(message["size_bytes"]) &&
      (typeof message["source_uuid"] === "string" ||
        message["source_uuid"] === null) &&
      (typeof message["source_uuid"] !== "string" ||
        isProtocolIdentifier(message["source_uuid"])) &&
      (typeof message["source_version"] === "string" ||
        message["source_version"] === null),
  ],
  [
    "FileTransferPart",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "source_component_uuid") &&
      Object.hasOwn(message, "transfer_uuid") &&
      Object.hasOwn(message, "part_index") &&
      Object.hasOwn(message, "content") &&
      message["type"] === "FileTransferPart" &&
      (typeof message["source_component_uuid"] === "string" ||
        message["source_component_uuid"] === null) &&
      (typeof message["source_component_uuid"] !== "string" ||
        isProtocolIdentifier(message["source_component_uuid"])) &&
      typeof message["transfer_uuid"] === "string" &&
      (typeof message["transfer_uuid"] !== "string" ||
        isProtocolIdentifier(message["transfer_uuid"])) &&
      Number.isSafeInteger(message["part_index"]) &&
      message["content"] instanceof Uint8Array,
  ],
  [
    "FileTransferAbort",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "transfer_uuid") &&
      Object.hasOwn(message, "reason") &&
      message["type"] === "FileTransferAbort" &&
      typeof message["transfer_uuid"] === "string" &&
      (typeof message["transfer_uuid"] !== "string" ||
        isProtocolIdentifier(message["transfer_uuid"])) &&
      typeof message["reason"] === "string",
  ],
  [
    "FileTransferPartAck",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 5 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "source_component_uuid") &&
      Object.hasOwn(message, "transfer_uuid") &&
      Object.hasOwn(message, "transferred_bytes") &&
      Object.hasOwn(message, "total_bytes") &&
      message["type"] === "FileTransferPartAck" &&
      (typeof message["source_component_uuid"] === "string" ||
        message["source_component_uuid"] === null) &&
      (typeof message["source_component_uuid"] !== "string" ||
        isProtocolIdentifier(message["source_component_uuid"])) &&
      typeof message["transfer_uuid"] === "string" &&
      (typeof message["transfer_uuid"] !== "string" ||
        isProtocolIdentifier(message["transfer_uuid"])) &&
      Number.isSafeInteger(message["transferred_bytes"]) &&
      Number.isSafeInteger(message["total_bytes"]),
  ],
  [
    "ClientPingMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 2 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "sent_ms") &&
      message["type"] === "ClientPingMessage" &&
      typeof message["sent_ms"] === "number" &&
      Number.isFinite(message["sent_ms"]),
  ],
  [
    "ServerPongMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 2 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "sent_ms") &&
      message["type"] === "ServerPongMessage" &&
      typeof message["sent_ms"] === "number" &&
      Number.isFinite(message["sent_ms"]),
  ],
  [
    "RegisterCommandMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "props") &&
      message["type"] === "RegisterCommandMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      isProtocolStruct30(message["props"]),
  ],
  [
    "CommandUpdateMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 3 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      Object.hasOwn(message, "updates") &&
      message["type"] === "CommandUpdateMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])) &&
      isProtocolMapping(message["updates"], (item) => isProtocolValue(item)),
  ],
  [
    "RemoveCommandMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 2 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      message["type"] === "RemoveCommandMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])),
  ],
  [
    "CommandTriggerMessage",
    (message) =>
      isProtocolRecord(message) &&
      Object.keys(message).length === 2 &&
      Object.hasOwn(message, "type") &&
      Object.hasOwn(message, "uuid") &&
      message["type"] === "CommandTriggerMessage" &&
      typeof message["uuid"] === "string" &&
      (typeof message["uuid"] !== "string" ||
        isProtocolIdentifier(message["uuid"])),
  ],
]);

/** Fail closed before a decoded batch reaches any stateful handler. */
export function validateMessage(message: unknown): asserts message is Message {
  if (!isProtocolRecord(message) || typeof message.type !== "string") {
    throw new Error("decoded payload contains an invalid message envelope");
  }
  const validator = messageValidators.get(message.type);
  if (validator === undefined) {
    throw new Error("decoded payload contains an unsupported message type");
  }
  if (!validator(message)) {
    throw new Error(
      `decoded ${message.type} does not match its protocol schema`,
    );
  }
}

/** Hash of the message schema this bundle was built against. Sent with
 * the version at connect, so a server running different code is turned
 * away with a reason instead of feeding the page fields it cannot read. */
export const LEIKA_PROTOCOL = "699295a8fc97";
