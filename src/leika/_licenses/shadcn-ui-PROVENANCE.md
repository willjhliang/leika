# Pinned shadcn/ui provenance

Leika's browser client was regenerated from the current shadcn default on
2026-07-24. The selected preset is Base UI + Nova with the neutral base color,
Geist font, Lucide icons, CSS variables, default radius, default menu color,
and subtle menu accent.

- Upstream: <https://github.com/shadcn-ui/ui>
- CLI package: `shadcn@4.14.1`
- Component registry: <https://ui.shadcn.com/r/styles/base-nova/>
- Initializer: <https://ui.shadcn.com/init?base=base&style=nova&baseColor=neutral&theme=neutral&iconLibrary=lucide&font=geist&rtl=false&menuAccent=subtle&menuColor=default&radius=default&track=1>
- License: MIT; see `shadcn-ui-LICENSE.md` in this directory.

The generated component source lives in
`src/leika/client/src/components/ui/`. The stock support stylesheet is
provided by the pinned npm package through `@import "shadcn/tailwind.css"`.
When the preset or CLI version changes, regenerate the components and update
this provenance in the same change.
