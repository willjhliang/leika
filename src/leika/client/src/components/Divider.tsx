import { Separator } from "@/components/ui/separator";
import { GuiDividerMessage } from "../WebsocketMessages";

function DividerComponent({ props }: GuiDividerMessage) {
  if (!props.visible) return null;
  return <Separator />;
}

export default DividerComponent;
