import { useViewer } from "./ViewerContext";
import { GuiModalMessage } from "./WebsocketMessages";
import GeneratedGuiContainer from "./ControlPanel/Generated";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "./components/ui/dialog";
import { shallowArrayEqual } from "./utils/shallowArrayEqual";

export function LeikaModal() {
  const viewer = useViewer();

  const modalList = viewer.useGui((state) => state.modals, shallowArrayEqual);
  const modals = modalList.map((conf) => {
    return <GeneratedModal key={conf.uuid} conf={conf} />;
  });

  return modals;
}

function GeneratedModal({ conf }: { conf: GuiModalMessage }) {
  const viewer = useViewer();
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (open) return;
        // Dismissing asks the server to close; it is the server that owns the
        // contained components and that takes the modal off screen, by echoing
        // this message back to every client. Removing it here too would leave
        // the components behind and hide the modal from this client alone.
        viewer.mutable.current.sendMessage({
          type: "GuiCloseModalMessage",
          uuid: conf.uuid,
        });
      }}
    >
      {/* Dialogs and their nested portals share one z-layer and stack by
          portal order. Raising only this popup would strand its own backdrop,
          previews, selects, and tooltips underneath it. */}
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{conf.title}</DialogTitle>
        </DialogHeader>
        <GeneratedGuiContainer containerUuid={conf.uuid} />
      </DialogContent>
    </Dialog>
  );
}
