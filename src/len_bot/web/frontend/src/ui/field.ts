import { computed, inject, type ComputedRef, type InjectionKey, type Ref } from 'vue'

/** What a Field gives the control inside it: the id its label points at, and its error state. */
export interface FieldContext {
  id: string
  invalid: Ref<boolean>
  describedBy: Ref<string | undefined>
  disabled: Ref<boolean>
}

export const fieldKey: InjectionKey<FieldContext> = Symbol('field')

/** Control props win over the surrounding Field, so a control also works on its own. */
export function useFieldControl(props: { id?: string; invalid?: boolean; disabled?: boolean }): {
  id: ComputedRef<string | undefined>
  invalid: ComputedRef<boolean>
  disabled: ComputedRef<boolean>
  describedBy: ComputedRef<string | undefined>
} {
  const field = inject(fieldKey, null)
  return {
    id: computed(() => props.id ?? field?.id),
    invalid: computed(() => props.invalid || field?.invalid.value || false),
    disabled: computed(() => props.disabled || field?.disabled.value || false),
    describedBy: computed(() => field?.describedBy.value),
  }
}
