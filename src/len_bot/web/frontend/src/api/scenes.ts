import { reactive } from 'vue'

/** Group names by scene id, filled from GET /api/host/scene-titles; a missing entry means the name is unknown. */
export const sceneTitles = reactive<Record<string, string>>({})
