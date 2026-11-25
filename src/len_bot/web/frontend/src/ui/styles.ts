/** Class lists shared by the form controls and floating layers, so every control has one frame and one focus ring. */
export const controlFrameBase = [
  'flex w-full min-w-0 items-center rounded-md border border-line-strong bg-surface text-ink',
  'transition-[border-color,box-shadow,background-color] duration-(--dur-1) ease-out',
  'hover:border-subtle focus-within:border-primary focus-within:shadow-focus',
  'data-invalid:border-error data-invalid:hover:border-error data-invalid:focus-within:border-error data-invalid:focus-within:shadow-error-focus',
  'data-readonly:bg-fill/55',
  'data-disabled:cursor-not-allowed data-disabled:bg-fill data-disabled:opacity-60 data-disabled:hover:border-line-strong',
  'pointer-coarse:text-lg',
].join(' ')

export const controlFrame = `${controlFrameBase} gap-2 px-3`

export const controlHeight = {
  sm: 'h-8 text-sm pointer-coarse:h-10',
  md: 'h-9 text-base pointer-coarse:h-11',
} as const

/** The text input inside a frame. Sixteen pixels on touch screens keeps iOS from zooming in. */
export const controlInput =
  'h-full min-w-0 flex-1 bg-transparent text-ink outline-none placeholder:text-subtle focus-visible:outline-none disabled:cursor-not-allowed'

export const floatingPanel =
  'ui-pop z-(--z-popover) overflow-hidden rounded-lg border border-line bg-surface-raised text-ink shadow-float'

export const menuItemBase = [
  'relative flex h-8 cursor-default items-center gap-2 rounded-sm text-sm outline-none select-none',
  'transition-colors duration-(--dur-1) data-disabled:pointer-events-none data-disabled:opacity-45 pointer-coarse:h-10',
].join(' ')
