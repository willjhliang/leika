import { GuiHtmlMessage } from "../WebsocketMessages";
import { guiHtmlSourceError } from "../rendererSourceLimits";

function HtmlComponent({ props }: GuiHtmlMessage) {
  const error = guiHtmlSourceError(props.content);
  if (error !== null) {
    return (
      <div className="text-sm text-muted-foreground" role="status">
        {error}
      </div>
    );
  }
  return <div dangerouslySetInnerHTML={{ __html: props.content }} />;
}

export default HtmlComponent;
