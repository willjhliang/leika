import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  NativeRadioGroupItem,
  RadioGroup,
  RadioGroupItem,
} from "@/components/ui/radio-group";
import { cn } from "@/lib/utils";
import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { MAX_GUI_COLLECTION_ITEM_CODE_UNITS } from "../guiLimits";
import { GuiRadioListMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";
import { EntryStack } from "./EntryStack";
import { HoverScrollText } from "./HoverScrollText";
import { ENTRY_BOX_CONTROLS, entryBoxClassName } from "./entryStackStyles";

/** One choice: what it says, and whether it is selected. */
type Item = GuiRadioListMessage["value"][number];

function FrozenItemRadio({
  id,
  place,
  item,
  disabled,
}: {
  id: string;
  place: number;
  item: Item;
  disabled: boolean;
}) {
  return (
    <RadioGroupItem
      id={id}
      value={String(place)}
      disabled={disabled}
      aria-label={item[0] || `Option ${place + 1}`}
      className="after:-inset-1"
      data-leika-radio-list-radio
    />
  );
}

function EditableItemRadio({
  id,
  name,
  place,
  item,
  disabled,
  onSelect,
}: {
  id: string;
  name: string;
  place: number;
  item: Item;
  disabled: boolean;
  onSelect: () => void;
}) {
  return (
    <NativeRadioGroupItem
      id={id}
      name={name}
      value={String(place)}
      checked={item[1]}
      disabled={disabled}
      aria-label={item[0] || `Option ${place + 1}`}
      className="after:-inset-1"
      onChange={(event) => {
        if (event.currentTarget.checked) onSelect();
      }}
      data-leika-radio-list-radio
    />
  );
}

/** An editable list of choices of which at most one can be selected.
 *
 * Its rows and frozen behavior deliberately match Checklist: editable choices
 * are one EntryStack, while frozen choices become words whose labels select
 * their radios. The value remains attached to each row as it moves.
 */
export default function RadioListComponent({
  uuid,
  value,
  props: { label, hint, disabled, frozen },
}: GuiRadioListMessage) {
  const { setValue } = useGuiComponent();
  const commit = (next: Item[]) => setValue(uuid, next);

  const rewrite = (place: number, item: Item) =>
    commit(value.map((other, where) => (where === place ? item : other)));

  const select = (place: number) =>
    commit(value.map(([text], where): Item => [text, where === place]));

  const selectedPlace = value.findIndex(([, selected]) => selected);
  const selectedValue = selectedPlace < 0 ? "" : String(selectedPlace);
  const onValueChange = (next: string) => {
    const place = Number(next);
    if (Number.isInteger(place) && place >= 0 && place < value.length) {
      select(place);
    }
  };

  const groupLabel = label ?? "Radio list";
  const stack = frozen ? (
    <RadioGroup
      value={selectedValue}
      onValueChange={onValueChange}
      disabled={disabled}
      aria-label={groupLabel}
      className="flex w-full min-w-0 flex-col gap-0"
    >
      {value.map((item, place) => (
        <div
          key={place}
          className={cn(
            "flex min-h-6 w-full min-w-0 items-center gap-2 pl-1",
            place > 0 && "-mt-px",
          )}
          data-leika-list-item
        >
          <FrozenItemRadio
            id={`${uuid}-${place}`}
            place={place}
            item={item}
            disabled={disabled}
          />
          <Label
            htmlFor={`${uuid}-${place}`}
            className={cn(
              "min-w-0 flex-1",
              disabled ? "opacity-50" : "cursor-pointer",
            )}
            title={item[0]}
            data-leika-radio-list-entry
          >
            <HoverScrollText>{item[0]}</HoverScrollText>
          </Label>
        </div>
      ))}
    </RadioGroup>
  ) : (
    // The editors deliberately live outside Base UI's RadioGroup. Native
    // same-name radios retain platform group semantics and arrow navigation
    // without taking the caret away from neighbouring text fields.
    <fieldset className="m-0 block w-full min-w-0 border-0 p-0">
      <legend className="sr-only">{groupLabel}</legend>
      <EntryStack
        items={value}
        commit={commit}
        blank={(): Item => ["", false]}
        disabled={disabled}
        frozen={false}
      >
        {(item, row) => (
          <>
            <Input
              value={item[0]}
              aria-label={`${label ?? "Radio list"} entry ${row.place + 1}`}
              className={cn(entryBoxClassName(row), ENTRY_BOX_CONTROLS, "pl-7")}
              disabled={disabled}
              maxLength={MAX_GUI_COLLECTION_ITEM_CODE_UNITS}
              onChange={(event) => {
                if (
                  event.currentTarget.value.length >
                  MAX_GUI_COLLECTION_ITEM_CODE_UNITS
                )
                  return;
                rewrite(row.place, [event.currentTarget.value, item[1]]);
              }}
              data-leika-radio-list-entry
            />
            <span className="absolute inset-y-0 left-1 z-20 flex items-center">
              <EditableItemRadio
                key={row.id}
                id={`${uuid}-${row.place}`}
                name={`leika-radio-list-${uuid}`}
                place={row.place}
                item={item}
                disabled={disabled}
                onSelect={() => select(row.place)}
              />
            </span>
          </>
        )}
      </EntryStack>
    </fieldset>
  );

  return (
    <GuiInputRow
      {...{ uuid, hint, label }}
      disabled={disabled}
      associateLabel={false}
      alignLabelToFirstRow
    >
      {stack}
    </GuiInputRow>
  );
}
