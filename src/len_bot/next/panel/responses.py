"""面板 JSON 响应；协议原文和持久化记录保留各自的 JSON 字段。"""

from pydantic import BaseModel, ConfigDict, JsonValue

from ..chat.schedule_store import Schedule

JsonObject = dict[str, JsonValue]
Number = int | float


class PanelResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Success(PanelResponse):
    success: bool


class LoginResult(Success):
    username: str
    is_default_password: bool


class CurrentUser(PanelResponse):
    username: str
    is_default_password: bool
    last_login_at: Number | None


class Status(PanelResponse):
    status: str


class Enabled(PanelResponse):
    enabled: bool


class Deleted(PanelResponse):
    deleted: bool


class PersonaName(PanelResponse):
    id: str
    name: str


class ScenePersona(PanelResponse):
    scene: str
    persona: PersonaName


class HostScene(ScenePersona):
    persona_path: str
    persona_switch: dict[str, str] | None
    voice_mode: str
    timezone: str
    chat_enabled: bool
    chat_status: JsonObject


class ServiceAlert(PanelResponse):
    name: str
    status: str
    error: str | None
    error_count: int
    latest_error: JsonValue


class HostState(PanelResponse):
    bot_id: str
    timezone: str
    delivery: str
    connection: JsonObject
    scenes: list[HostScene]
    send_hold: bool
    memory_backend: str | None
    plugins: list[ServiceAlert] | None
    mcp: list[ServiceAlert]


class SceneTitles(PanelResponse):
    titles: dict[str, str]
    errors: dict[str, str]
    members: dict[str, int]


class LogPage(PanelResponse):
    items: list[JsonObject]
    directory: str
    limit: int


class SceneState(ScenePersona):
    timezone: str
    bot_id: str
    delivery: str
    voice_mode: str
    models: dict[str, str]
    messages: list[JsonObject]
    turns: list[JsonObject]


class TrialState(SceneState):
    running: bool
    error: str | None


class SessionPage(PanelResponse):
    scene: str
    timezone: str
    active_only: bool
    recap: str | None
    compact_through: int
    last_message_seq: int
    entries: list[JsonObject]
    next_before: int | None


class HistoryAction(PanelResponse):
    compact_through: int
    message: str | None = None
    turn_id: str | None = None
    recap: str | None = None


class RecordPage(PanelResponse):
    items: list[JsonObject]
    next_offset: int | None = None
    total: int | None = None
    limit: int | None = None
    offset: int | None = None


class Records(PanelResponse):
    items: list[JsonObject]


class SettingsSnapshot(PanelResponse):
    running: JsonObject
    saved: JsonObject
    versions: dict[str, str]
    restart_required: JsonObject


class LearningSettingsSnapshot(PanelResponse):
    scene: str
    running: JsonObject | None
    saved: JsonObject | None
    restart_required: bool


class Protocols(PanelResponse):
    protocols: list[JsonObject]


class ModelList(PanelResponse):
    models: list[JsonObject]


class ModelProbe(PanelResponse):
    model: str
    text: str
    kind: str
    calls: int
    usage: list[JsonValue]
    scope: str
    dimensions: int | None = None


class MemoryState(PanelResponse):
    enabled: bool
    backend: str | None
    actions: list[str]
    public_writable: bool
    public_readable: bool
    auto_recall: bool
    recall_budget_chars: int | None
    summaries: bool
    reindexing: bool
    index: JsonObject | None
    reindex_command: str
    maintenance_container: bool
    scenes: list[ScenePersona]
    persona_ids: dict[str, list[str]]


class ReindexedFiles(PanelResponse):
    files: int


class ReindexedExpressions(PanelResponse):
    expressions: int


class MemoryHistory(PanelResponse):
    changes: list[JsonObject]


class MemoryHit(PanelResponse):
    scope: str
    path: str
    preview: str
    total_chars: int
    sections: list[JsonObject]
    score: Number | None


class MemorySearch(PanelResponse):
    hits: list[MemoryHit]


class MemorySummary(PanelResponse):
    enabled: bool
    summary: JsonObject
    runs: list[JsonObject]


class MemorySources(PanelResponse):
    snapshot: int
    offset: int
    next_offset: int | None
    previews: list[JsonObject]


class IngestState(PanelResponse):
    enabled: bool
    scenes: list[JsonObject]


class IngestAction(PanelResponse):
    requested: str
    state: JsonObject | None = None
    job: JsonValue = None


class EmbeddingCalls(PanelResponse):
    source: str
    snapshot: int
    offset: int
    next_offset: int | None
    calls: list[JsonObject]
    read_at: Number


class EmbeddingCall(PanelResponse):
    read_at: Number
    call: JsonObject


class Role(PanelResponse):
    key: str
    path: str
    config_path: str
    id: str | None
    name: str | None
    brief: str | None
    aliases: list[str]
    error: str | None
    avatar: bool
    duplicate_id: bool
    scenes: list[str]
    running_scenes: list[str]


class RoleLibrary(PanelResponse):
    roles: list[Role]


class RoleDeleted(PanelResponse):
    moved_to: str


class RoleScenes(PanelResponse):
    results: list[JsonObject]


class RoleLocation(PanelResponse):
    saved_path: str
    running_path: str
    affected_scenes: list[str]


class Applied(PanelResponse):
    applied: bool | None = None
    apply_error: str | None = None


class RoleProfile(Applied):
    directory: str
    id: str
    profile: JsonObject
    affected_scenes: list[str]


class RoleFiles(Applied):
    saved: dict[str, str]
    running: JsonObject | None
    saved_path: str
    affected_scenes: list[str]
    appended: JsonObject | None = None


class KnowledgeDocument(PanelResponse):
    filename: str
    saved_path: str
    content: str
    tags: list[str]


class KnowledgeFile(PanelResponse):
    filename: str
    tags: list[str]
    chars: int


class RoleKnowledge(Applied):
    key: str
    saved_path: str
    saved_persona: PersonaName
    affected_scenes: list[str]
    document: KnowledgeDocument | None
    files: list[KnowledgeFile]


class RoleAvatar(Applied):
    directory: str
    saved: JsonObject
    affected_scenes: list[str]


class RoleStickers(Applied):
    key: str
    saved_path: str
    index_content: str | None
    files: list[JsonObject]
    entries: list[JsonObject] | None
    affected_scenes: list[str]


class RoleAbilities(PanelResponse):
    key: str
    directory: str
    scene: str
    affected_scenes: list[str]
    tools: JsonObject
    skills: JsonObject


class RolePermission(Applied):
    directory: str
    persona: PersonaName
    saved: str | list[str]
    affected_scenes: list[str]
    running: str | list[str] | None = None
    restart_required: bool | None = None


class Capabilities(ScenePersona):
    scenes: list[ScenePersona]
    persona: JsonObject
    role_tools: JsonObject
    tools: list[JsonObject]
    services: dict[str, bool]
    not_implemented: list[str]


class Skills(PanelResponse):
    scene: str
    directory: str | None
    running_directory: str | None
    role_skills: JsonObject
    catalog: list[JsonObject]
    running: list[JsonObject]


class PluginSnapshot(PanelResponse):
    running: JsonObject
    available: dict[str, list[JsonObject]]
    discovery_errors: list[JsonValue]
    saved: JsonObject
    retained_data: list[JsonObject]
    scene_choices: list[str]
    scenes: dict[str, JsonObject]
    restart_required: bool
    operation: JsonValue = None


class PluginHealth(PanelResponse):
    plugins: list[JsonObject]


class McpState(PanelResponse):
    saved: dict[str, JsonObject]
    scenes: list[str]
    restart_required: bool
    running: list[JsonObject]
    result: JsonValue = None
    binding: str | None = None


class PromptSummary(PanelResponse):
    version: str
    edited_version: str | None
    keep_on_update: bool
    items: list[JsonObject]


class PromptDocument(PanelResponse):
    name: str
    default: str
    text: str
    edited: bool
    placeholders: list[str]


class ScheduleState(PanelResponse):
    timezone: str
    scenes: list[JsonObject]


class SchedulePage(PanelResponse):
    items: list[Schedule]
    next_offset: int | None


class ProactivePage(PanelResponse):
    scene: str
    timezone: str
    now: Number
    settings: JsonObject | None
    idle_since: Number | None
    pause: JsonObject | None
    next_at: Number | None
    next_reason: str | None
    items: list[JsonObject]
    next_offset: int | None


class AudioPage(RecordPage):
    automatic: bool
    timezone: str
    limits: JsonObject
    onebot_ws_frame_bytes: int | None
    available: bool
    worker_error: str | None
    stopping: bool


class TaskState(PanelResponse):
    configured: bool
    timezone: str
    accepting: bool
    error: str | None
    scenes: list[JsonObject]
    public_network: bool
    file_upload: bool


class TaskPool(PanelResponse):
    configured: bool
    usage: JsonObject | None


class TaskStoragePage(RecordPage):
    scene: str
    measured: bool


class TaskStorage(PanelResponse):
    scene: str
    task_id: int
    started_at: Number
    ended_at: Number
    status_at_start: str
    status_at_end: str
    container_at_start: str | None
    container_at_end: str | None
    task: JsonObject
    continuation: str
    cleanable: bool
    roots: list[JsonObject]
    temporary: list[JsonObject]
    last_cleanup: JsonObject | None
    hard_disk_quota: JsonValue
    notice: str


class TaskCleanup(PanelResponse):
    scene: str
    operation: str
    items: list[JsonObject]


class TaskSkills(PanelResponse):
    task_id: int
    scene: str
    items: list[JsonObject]
    notice: str


class SkillFiles(PanelResponse):
    skill: JsonObject
    files: list[JsonObject]
    used_by_running: list[str]
    referenced_by_saved: list[str]


class SkillMoved(PanelResponse):
    skill: JsonObject
    moved_from: str
    moved_to: str
    files: int
    bytes: int
    affected_scenes: list[str]
    restart_required: bool


class SkillDeleted(PanelResponse):
    deleted: str
    name: str
    source: str
    affected_scenes: list[str]


class TrialInfo(PanelResponse):
    id: str
    scene: str
    created: Number
    stopped: Number | None
    context: list[str]
    active: bool
    root: str
    excluded_tools: list[str]
    memory: str
    persona: str
    persona_source: str
    draft_path: str | None
    models: dict[str, str]


class TrialList(PanelResponse):
    items: list[TrialInfo]


class UpdateState(PanelResponse):
    version: str
    managed: bool
    status: JsonValue
    check: JsonObject
    notice: list[str] | None
    rollback_loses_data: bool


class SetupProtocols(Protocols):
    container: bool
    panel_port: int | None


class SetupPlatform(PanelResponse):
    bot_id: str


class SetupPlugins(PanelResponse):
    plugins: list[JsonObject]


class SetupSaved(PanelResponse):
    saved: bool
    config: str
    persona: str
    panel_url: str
    panel_port: int
    delivery: str
    voice_mode: str
    next: str
    plugins: list[JsonValue]


class Overview(PanelResponse):
    timezone: str
    sampled_at: Number
    since: Number
    until: Number
    messages: JsonObject
    turns: JsonObject
    model_calls: int
    unfinished_calls: int
    tokens: JsonObject
    unknown_token_calls: int
    pending_schedules: int
    recent_errors: list[JsonObject]
    reply_effects: JsonObject
    undelivered: JsonObject
    pending_reviews: JsonObject
    hourly: JsonObject
    activity: list[JsonObject]
    failed_tasks: JsonObject
    memory_stuck: list[JsonObject]
    speech_held: dict[str, Number]
    memory_index: JsonObject | None


class LoopHealth(PanelResponse):
    running: bool
    started_at: Number | None
    interval_ms: int
    threshold_ms: int
    probes: int
    stalls: int
    pauses: int
    stalled_ms_total: int
    max_lag_ms: int
    recent: list[JsonObject]


class PendingRestart(PanelResponse):
    plugins: list[JsonObject]
    sections: list[str]
    scenes: list[str]
    personas: list[JsonValue]
    maintenance: list[dict[str, str]]


class Ready(PanelResponse):
    pid: int
    started_at: Number
    version: str
    status: str
    ready: bool
    platform: JsonObject | None


class RestartPreview(PanelResponse):
    process: JsonObject
    restartable: bool
    intent: str
    pending: PendingRestart
    panel: JsonObject
    chats: list[str]
    tasks: list[JsonObject]
    queued_tasks: int
    browsers: list[JsonObject]
    trials: list[JsonObject]


class SceneControl(PanelResponse):
    scene: str
    timezone: str
    attention: JsonObject
    temporary_quiet: JsonObject | None
    paused: bool
    quiet_until: Number | None
    direct: str
    scope: str


class AllChatControl(Enabled):
    scenes: int


class RetentionState(PanelResponse):
    enabled: bool
    busy: bool
    last_result: JsonObject | None
    error: str | None
    preview: JsonObject | None


class SceneLimit(PanelResponse):
    scene: str
    blocked: bool
    reason: str | None
    until: Number | None
    speech: JsonObject


class Limits(PanelResponse):
    limits: JsonObject
    scenes: list[SceneLimit]
    scope: str


class Usage(PanelResponse):
    timezone: str
    period: str
    since: Number
    until: Number
    calls: int
    unfinished_calls: int
    settled_unknown_calls: int
    successful_unknown_calls: int
    budgeted: JsonObject
    input: int
    output: int
    cached: int
    known_calls: int
    unknown_calls: int
    groups: list[JsonObject]
    unverified_summary_attempts: int
    unmetered_sources: list[str]
    wakes: list[JsonObject]
    scope: str
    memory_record_source: str


class LogFiles(Enabled):
    timezone: str
    items: list[JsonObject]


class Permissions(PanelResponse):
    running: JsonObject
    saved: JsonObject
    restart_required: bool
    owners: list[str]
    effective_identities: JsonObject


class LearningState(PanelResponse):
    scene: str
    enabled: bool
    index: JsonObject | None
    reindex_command: str
    maintenance_container: bool
    selection_enabled: bool
    voice_mode: str
    settings: JsonObject | None
    cursor: JsonObject | None
    latest: JsonObject | None
    expression_counts: dict[str, int]
    service_state: JsonObject | None


class JargonState(PanelResponse):
    scene: str
    enabled: bool
    selection_enabled: bool
    cursor: JsonObject | None
    service_state: JsonObject | None


class StickerState(PanelResponse):
    scene: str
    enabled: bool
    service_state: JsonObject | None
    counts: dict[str, int]


class ReplyEffectsState(PanelResponse):
    scene: str
    enabled: bool
    days: int
    delivery: str
    settings: JsonObject | None
    distribution: JsonObject
    service_state: JsonObject | None


class Requested(PanelResponse):
    requested: bool
    state: JsonObject | None = None
    candidate: JsonObject | None = None


class LearningRequested(PanelResponse):
    requested: str
    state: JsonObject | None


class RoleDraft(PanelResponse):
    directory: str
    files: dict[str, str]
    profile: JsonObject


class RoleImported(PanelResponse):
    path: str
    config_path: str
    persona: JsonObject
    files: int
    examples: int
    knowledge: int
    stickers: int
    bound: bool
    notice: str | None = None


class MaterialListing(PanelResponse):
    directory: str
    exists: bool
    files: list[JsonObject]
    scene: str
    notice: str


class SharedFile(PanelResponse):
    directory: str
    name: str
    path: str
    size: int


class MaterialAdopted(SharedFile):
    source_task_id: int
    source_file_id: int
    source_path: str
    source_preserved: bool
    copied: bool
    scene: str
    notice: str


class ResourceDeleted(PanelResponse):
    reference: JsonObject
    name: str
    size: int
    removed: bool


class Pairing(PanelResponse):
    pairing_link: str


class BrowserDevices(PanelResponse):
    devices: list[JsonObject]


class BrowserRevoked(PanelResponse):
    revoked: str


class MemoryChange(PanelResponse):
    action: str
    path: str
    changed_at: Number
    reason: str
    before: str | None
    after: str | None


class MemoryAdopted(PanelResponse):
    source: str
    target: str
    target_saved: bool
    source_removed: bool
    change: MemoryChange
    notice: str


class MemoryForgotten(PanelResponse):
    path: str
    removed_current: bool
    removed_history_versions: int
    removed_summaries: list[str]
    excluded_records: list[int]
    new_exclusions: int


class TrialSettings(PanelResponse):
    scene: str
    timezone: str
    bot_id: str
    voice_mode: str
    delivery: str
    scene_persona: JsonObject
    persona: JsonObject
    selected_examples: list[JsonObject]
    knowledge: list[JsonObject]
    tools: JsonObject


class ScenePersonaResult(PanelResponse):
    saved: JsonObject
    restart_required: bool


class MessageReceipt(PanelResponse):
    status: str
    message_seq: int
    platform_message_id: str | None
    wake_channel: str | None
    wake_verdict: JsonObject
    addressed_to_others: bool | None = None
    reason: str | None = None
    paused: bool | None = None
    quiet_until: str | None = None


class StoredTurn(PanelResponse):
    turn: JsonObject
    calls: list[JsonObject]
