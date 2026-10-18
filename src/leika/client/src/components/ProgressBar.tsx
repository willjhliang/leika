import { Progress } from "@/components/ui/progress";
import { GuiProgressBarMessage } from "../WebsocketMessages";

export default function ProgressBarComponent({
  props: { value, animated },
}: GuiProgressBarMessage) {
  return (
    <Progress
      className={animated ? "animate-pulse" : undefined}
      value={value}
    />
  );
}
