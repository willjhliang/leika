import { Progress } from "@/components/ui/progress";
import { GuiProgressBarMessage } from "../WebsocketMessages";

export default function ProgressBarComponent({
  value,
  props: { animated, visible },
}: GuiProgressBarMessage) {
  if (!visible) return null;
  return (
    <Progress
      className={animated ? "animate-pulse" : undefined}
      value={value}
    />
  );
}
