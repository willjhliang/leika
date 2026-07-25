import { FileTextIcon, KeyboardIcon, MenuIcon } from "lucide-react";
import React from "react";

import { Button } from "./components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "./components/ui/sheet";
import { ViewerContext } from "./ViewerContext";
import { ThemeConfigurationMessage } from "./WebsocketMessages";
import { useColorScheme } from "./hooks/useColorScheme";

type ArrayElement<ArrayType extends readonly unknown[]> =
  ArrayType extends readonly (infer ElementType)[] ? ElementType : never;
type TitlebarContent = NonNullable<
  ThemeConfigurationMessage["titlebar_content"]
>;
type TitlebarButtonData = ArrayElement<NonNullable<TitlebarContent["buttons"]>>;

function assertUnreachable(value: never): never {
  throw new Error("Unexpected titlebar icon: " + value);
}

/** Lucide dropped brand marks in v1, so GitHub ships as a local glyph. */
function GitHubIcon(props: React.ComponentPropsWithoutRef<"svg">) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden {...props}>
      <path d="M12 .5C5.73.5.5 5.73.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.56 0-.28-.01-1.02-.02-2-3.2.69-3.87-1.54-3.87-1.54-.53-1.33-1.29-1.69-1.29-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.79 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.12 3.05.74.8 1.19 1.83 1.19 3.09 0 4.42-2.7 5.39-5.27 5.68.42.36.79 1.07.79 2.15 0 1.55-.02 2.8-.02 3.18 0 .31.21.68.8.56A11.51 11.51 0 0 0 23.5 12C23.5 5.73 18.27.5 12 .5Z" />
    </svg>
  );
}

function getIcon(icon: TitlebarButtonData["icon"]) {
  switch (icon) {
    case null:
      return null;
    case "GitHub":
      return GitHubIcon;
    case "Description":
      return FileTextIcon;
    case "Keyboard":
      return KeyboardIcon;
    default:
      return assertUnreachable(icon);
  }
}

export function TitlebarButton(props: TitlebarButtonData) {
  const Icon = getIcon(props.icon);
  return (
    <Button
      variant="outline"
      size="sm"
      render={
        <a href={props.href || undefined} target="_blank" rel="noreferrer" />
      }
    >
      {Icon === null ? null : <Icon data-icon="inline-start" />}
      {props.text}
    </Button>
  );
}

export function MobileTitlebarButton(props: TitlebarButtonData) {
  const Icon = getIcon(props.icon);
  return (
    <Button
      variant="ghost"
      className="w-full justify-start"
      render={
        <a href={props.href || undefined} target="_blank" rel="noreferrer" />
      }
    >
      {Icon === null ? null : <Icon data-icon="inline-start" />}
      {props.text}
    </Button>
  );
}

export function TitlebarImage({
  image,
}: {
  image: NonNullable<TitlebarContent["image"]>;
}) {
  // Follows the resolved scheme, so a URL-forced or embedded dark workspace
  // gets the dark artwork even when the server theme says light.
  const colorScheme = useColorScheme();
  const source =
    image.image_url_dark == null || colorScheme === "light"
      ? image.image_url_light
      : image.image_url_dark;
  const rendered = (
    <img src={source} alt={image.image_alt} className="block h-7 w-auto" />
  );
  return image.href == null ? (
    rendered
  ) : (
    <a href={image.href} className="block">
      {rendered}
    </a>
  );
}

export function Titlebar() {
  const viewer = React.useContext(ViewerContext)!;
  const content = viewer.useGui((state) => state.theme.titlebar_content);
  const [menuOpen, setMenuOpen] = React.useState(false);

  if (content == null) return null;
  const buttons = content.buttons;

  return (
    <header className="z-10 h-14 shrink-0 border-b bg-background">
      <div className="mx-auto flex h-full w-full max-w-7xl items-center gap-4 px-4">
        <div className="mr-auto flex items-center">
          {content.image === null ? null : (
            <TitlebarImage image={content.image} />
          )}
        </div>
        <nav className="hidden min-w-0 items-center gap-2 overflow-x-auto sm:flex">
          {buttons?.map((button, index) => (
            <TitlebarButton {...button} key={index} />
          ))}
        </nav>
        <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
          <SheetTrigger
            render={
              <Button
                variant="ghost"
                size="icon"
                className="sm:hidden"
                aria-label="Open navigation"
              />
            }
          >
            <MenuIcon />
          </SheetTrigger>
          <SheetContent side="right">
            <SheetHeader>
              <SheetTitle>Navigation</SheetTitle>
            </SheetHeader>
            <nav className="grid gap-2 px-4">
              {buttons?.map((button, index) => (
                <MobileTitlebarButton {...button} key={index} />
              ))}
            </nav>
          </SheetContent>
        </Sheet>
      </div>
    </header>
  );
}
