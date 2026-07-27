import { ViewerContext } from "./ViewerContext";
import { GuiModalMessage } from "./WebsocketMessages";
import GeneratedGuiContainer from "./ControlPanel/Generated";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "./components/ui/dialog";
import { useContext } from "react";
import { shallowArrayEqual } from "./utils/shallowArrayEqual";

export function LeikaModal() {
  const viewer = useContext(ViewerContext)!;

  const modalList = viewer.useGui((state) => state.modals, shallowArrayEqual);
  const modals = modalList.map((conf, index) => {
    return <GeneratedModal key={conf.uuid} conf={conf} index={index} />;
  });

  return modals;
}

function GeneratedModal({
  conf,
  index,
}: {
  conf: GuiModalMessage;
  index: number;
}) {
  const viewer = useContext(ViewerContext)!;
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
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg"
        style={{ zIndex: 100 + index }}
      >
        <DialogHeader>
          <DialogTitle>{conf.title}</DialogTitle>
        </DialogHeader>
        <GeneratedGuiContainer containerUuid={conf.uuid} />
      </DialogContent>
    </Dialog>
  );
}
