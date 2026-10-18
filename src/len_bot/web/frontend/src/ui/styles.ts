/** Class lists shared by the form controls and floating layers, so every control has one frame and one focus ring. */
export const controlFrame = [
  'flex w-full min-w-0 items-center gap-2 rounded-md border border-line-strong bg-surface px-3 text-base text-ink',
  'transition-[border-color,box-shadow,background-color] duration-150 ease-out',
  'hover:border-subtle focus-within:border-primary focus-within:shadow-[0_0_0_3px_var(--focus-ring)]',
  'data-invalid:border-error data-invalid:focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--error)_20%,transparent)]',
  'data-disabled:cursor-not-allowed data-disabled:bg-fill data-disabled:opacity-60 data-disabled:hover:border-line-strong',
  'pointer-coarse:text-lg',
].join(' ')

export const controlHeight = { sm: 'h-8', md: 'h-9 pointer-coarse:h-11' } as const

/** The text input inside a frame. Sixteen pixels on touch screens keeps iOS from zooming in. */
export const controlInput =
  'h-full min-w-0 flex-1 bg-transparent text-ink outline-none placeholder:text-subtle focus-visible:outline-none disabled:cursor-not-allowed'

export const floatingPanel =
  'ui-pop z-(--z-popover) overflow-hidden rounded-lg border border-line bg-surface-raised text-ink shadow-float'

export const menuItem = [
  'relative flex h-8 cursor-default items-center gap-2 rounded-sm px-2 text-sm outline-none select-none',
  'data-highlighted:bg-hover data-disabled:pointer-events-none data-disabled:opacity-45 pointer-coarse:h-10',
].join(' ')
