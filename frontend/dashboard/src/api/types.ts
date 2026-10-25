export type DataMode = 'mock' | 'live';
export type DemoScenario = 'normal' | 'loading' | 'empty' | 'unauthenticated' | 'forbidden' | 'reauth' | 'outage';
export type PolicyStatus = 'allow' | 'deny' | 'require_approval';
export type PolicyReason =
  | 'allowed' | 'unknown_tool' | 'target_not_allowlisted' | 'permission_missing' | 'invalid_arguments'
  | 'approval_required' | 'approval_rejected' | 'approval_mismatch' | 'approval_expired';
export type RiskLevel = 'low' | 'medium' | 'high';

export interface ProposedAction {
  action_id: string;
  tool_name: string;
  target_ref: string;
  arguments: Record<string, unknown>;
  purpose: string;
  idempotency_key?: string | null;
  requested_at: string;
}
export interface ActionValidation { status: PolicyStatus; reason: PolicyReason; action_hash: string | null; risk: RiskLevel | null }
export interface PolicyCheck { action: ProposedAction; result: ActionValidation; at: string }
export interface ChatResponse {
  conversation_id: string | null;
  answer: string | null;
  proposed_actions: ProposedAction[];
  model?: string | null;
  memory_used?: string[];
  connectors_used?: string[];
}

export type FailureKind = 'unavailable' | 'unauthenticated' | 'forbidden' | 'invalid' | 'rate_limited' | 'network' | 'server';
export interface Failure { ok: false; kind: FailureKind; message: string; code?: string; details?: unknown; status?: number; requestId?: string }
export type Result<T> = { ok: true; data: T } | Failure;

export interface Probe { state: 'ok' | 'degraded' | 'unreachable'; detail?: string; ms?: number }
export interface Principal { id: string; display_name: string; authenticated: boolean }
export interface HealthSnapshot {
  health: Probe;
  ready: Probe;
  principalCheck: Probe;
  principal: Principal | null;
  checkedAt: string;
  simulated: boolean;
}

export type MemoryKind = 'fact' | 'preference' | 'context' | 'episode' | 'skill';
export interface MemoryRecord { id: string; content: string; kind: MemoryKind; source: string; inferred: boolean; confidence: number; createdAt: string }
export interface CreateMemory { content: string; kind: MemoryKind }
export type JobStatus = 'queued' | 'running' | 'retry_wait' | 'awaiting_approval' | 'succeeded' | 'failed' | 'cancelled';
export interface JobRecord { id: string; name: string; status: JobStatus; startedAt: string; durationS: number | null; attempts: number; outcome: string }
export type Severity = 'critical' | 'high' | 'medium' | 'low';
export interface Finding { id: string; severity: Severity; title: string; resource: string; detail: string; status: 'open' | 'resolved'; foundAt: string }
export interface GitHubRepository { full_name: string; name: string; owner: string; private?: boolean; html_url?: string }
export interface GitHubIssue { number: number; title: string; state: string; html_url?: string; created_at?: string }
export interface GitHubPullRequest extends GitHubIssue { draft?: boolean; head_ref?: string; base_ref?: string }
export interface GitHubWorkflowRun { id: number | string; name: string; status: string; conclusion: string | null; created_at: string; html_url?: string }
export interface CalendarEvent { id: string; summary: string; start: string; end: string; timezone: string }
export interface Note { id: string; title: string; content: string; created_at: string; updated_at: string }

export type Feature = 'health' | 'chat' | 'actions' | 'memory' | 'jobs' | 'guardian' | 'integrations';
export type Support = 'live' | 'simulated' | 'unavailable';

export interface Api {
  mode: DataMode;
  support: Record<Feature, Support>;
  health(): Promise<Result<HealthSnapshot>>;
  validateAction(action: ProposedAction): Promise<Result<ActionValidation>>;
  recentPolicyChecks(): PolicyCheck[];
  sendChat(message: string, conversationId: string | null): Promise<Result<ChatResponse>>;
  listMemories(): Promise<Result<MemoryRecord[]>>;
  createMemory(memory: CreateMemory): Promise<Result<MemoryRecord>>;
  forgetMemory(id: string): Promise<Result<void>>;
  listJobs(): Promise<Result<JobRecord[]>>;
  listFindings(): Promise<Result<Finding[]>>;
  listGithubRepos(): Promise<Result<GitHubRepository[]>>;
  listGithubIssues(repo: string): Promise<Result<GitHubIssue[]>>;
  listGithubPulls(repo: string): Promise<Result<GitHubPullRequest[]>>;
  listGithubRuns(repo: string): Promise<Result<GitHubWorkflowRun[]>>;
  listCalendarEvents(start: string, end: string, timezone: string): Promise<Result<CalendarEvent[]>>;
  listNotes(): Promise<Result<Note[]>>;
  createNote(title: string, content: string): Promise<Result<Note>>;
  updateNote(id: string, title: string, content: string): Promise<Result<Note>>;
  deleteNote(id: string): Promise<Result<void>>;
}
