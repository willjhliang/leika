import { MenuIcon } from "lucide-react";
import React from "react";

import { IconHtml } from "./components/common";
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

export function TitlebarButton(props: TitlebarButtonData) {
  return (
    <Button
      variant="outline"
      size="sm"
      render={
        <a href={props.href || undefined} target="_blank" rel="noreferrer" />
      }
    >
      {props.icon_html === null ? null : <IconHtml html={props.icon_html} />}
      {props.text}
    </Button>
  );
}

export function MobileTitlebarButton(props: TitlebarButtonData) {
  return (
    <Button
      variant="ghost"
      className="w-full justify-start"
      render={
        <a href={props.href || undefined} target="_blank" rel="noreferrer" />
      }
    >
      {props.icon_html === null ? null : <IconHtml html={props.icon_html} />}
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
