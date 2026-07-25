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
  return (
    <Dialog
      open
      onOpenChange={() => {
        // To make memory management easier, we should only close modals from
        // the server.
        // Otherwise, the client would need to communicate to the server that
        // the modal was deleted and contained GUI elements were cleared.
      }}
    >
      <DialogContent
        showCloseButton={false}
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
