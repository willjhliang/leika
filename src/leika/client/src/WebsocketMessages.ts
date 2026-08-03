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
    color: "primary" | "secondary";
    _icon_html: string | null;
    _hold_callback_freqs: number[];
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
    color: "primary" | "secondary";
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
    color: "primary" | "secondary";
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
    color: ("primary" | "secondary")[];
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
    color: ("primary" | "secondary")[];
    options: string[];
    _merge: boolean[];
  };
}
/** Sent server->client to remove a GUI element.
 *
 * (automatically generated)
 */
export interface GuiRemoveMessage {
  type: "GuiRemoveMessage";
  uuid: string;
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
/** GuiCloseModalMessage(uuid: 'str')
 *
 * (automatically generated)
 */
export interface GuiCloseModalMessage {
  type: "GuiCloseModalMessage";
  uuid: string;
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
  pane_id: string;
  updates: { [key: string]: any };
}
/** Remove a pane.
 *
 * (automatically generated)
 */
export interface ViewportPaneRemoveMessage {
  type: "ViewportPaneRemoveMessage";
  pane_id: string;
}
/** Authoritative pane IDs used to reconcile browser-persisted layouts.
 *
 * (automatically generated)
 */
export interface ViewportPaneSnapshotMessage {
  type: "ViewportPaneSnapshotMessage";
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
/** Message from server->client to configure parts of the GUI.
 *
 * (automatically generated)
 */
export interface ThemeConfigurationMessage {
  type: "ThemeConfigurationMessage";
  titlebar_content: {
    buttons:
      | { text: string | null; icon_html: string | null; href: string | null }[]
      | null;
    image: {
      image_url_light: string;
      image_url_dark: string | null;
      image_alt: string;
      href: string | null;
    } | null;
  } | null;
  control_layout: "floating" | "collapsible" | "fixed";
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
  disposition: "save" | "link" | "preview";
  transfer_uuid: string;
  filename: string;
  mime_type: string;
  part_count: number;
  size_bytes: number;
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
/** Message from server->client to set the label of the GUI panel.
 *
 * (automatically generated)
 */
export interface SetGuiPanelLabelMessage {
  type: "SetGuiPanelLabelMessage";
  label: string | null;
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
  | GuiModalMessage
  | GuiCloseModalMessage
  | GuiButtonHoldMessage
  | GuiUpdateMessage
  | ViewportImageMessage
  | ViewportMatplotlibMessage
  | ViewportPlotlyMessage
  | ViewportViserMessage
  | ViewportPaneUpdateMessage
  | ViewportPaneRemoveMessage
  | ViewportPaneSnapshotMessage
  | WorkspaceConfigurationMessage
  | ThemeConfigurationMessage
  | FileTransferStartUpload
  | FileTransferStartDownload
  | FileTransferPart
  | FileTransferPartAck
  | ClientPingMessage
  | ServerPongMessage
  | SetGuiPanelLabelMessage
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
