import { GuiHtmlMessage } from "../WebsocketMessages";

function HtmlComponent({ props }: GuiHtmlMessage) {
  return <div dangerouslySetInnerHTML={{ __html: props.content }} />;
}

export default HtmlComponent;
