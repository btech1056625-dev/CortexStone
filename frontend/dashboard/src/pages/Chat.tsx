import { useEffect, useMemo, useRef, useState } from 'react';
import { FileJson2, RefreshCw, Send, ShieldCheck } from 'lucide-react';
import { api } from '../app-context';
import type { ActionValidation, Failure, PolicyCheck, ProposedAction } from '../api/types';
import { Modal } from '../dialog';
import { Badge, Banner, Empty, PageHeader } from '../ui';

interface Msg {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  actions?: ProposedAction[];
  model?: string | null;
  memoryUsed?: string[];
  connectorsUsed?: string[];
  status?: 'sending' | 'failed';
  error?: string;
}

function promptFromHash() {
  return new URLSearchParams(location.hash.split('?')[1] ?? '').get('prompt') ?? '';
}

export default function Chat() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [draft, setDraft] = useState(promptFromHash);
  const [busy, setBusy] = useState(false);
  const [conv, setConv] = useState<string | null>(null);
  const [selectedActionId, setSelectedActionId] = useState<string | null>(null);
  const [validation, setValidation] = useState<ActionValidation | null>(null);
  const [validationFailure, setValidationFailure] = useState<Failure | null>(null);
  const [validating, setValidating] = useState(false);
  const [inspect, setInspect] = useState<PolicyCheck | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const enabled = api.support.chat !== 'unavailable';
  const actions = useMemo(() => msgs.flatMap((message) => message.actions ?? []), [msgs]);
  const selectedAction = actions.find((action) => action.action_id === selectedActionId) ?? actions[0] ?? null;

  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [msgs, busy]);
  useEffect(() => {
    const onHashChange = () => {
      const prompt = promptFromHash();
      if (prompt) setDraft(prompt);
    };
    addEventListener('hashchange', onHashChange);
    return () => removeEventListener('hashchange', onHashChange);
  }, []);
  useEffect(() => {
    if (selectedAction && !selectedActionId) setSelectedActionId(selectedAction.action_id);
  }, [selectedAction, selectedActionId]);

  async function deliver(id: string, text: string) {
    setBusy(true);
    setMsgs((messages) => messages.map((message) => message.id === id ? { ...message, status: 'sending', error: undefined } : message));
    const result = await api.sendChat(text, conv);
    setBusy(false);
    if (!result.ok) {
      setMsgs((messages) => messages.map((message) => message.id === id ? { ...message, status: 'failed', error: result.message } : message));
      return;
    }
    setConv(result.data.conversation_id ?? conv);
    const assistant: Msg = {
      id: crypto.randomUUID(), role: 'assistant', text: result.data.answer ?? '',
      actions: result.data.proposed_actions, model: result.data.model,
      memoryUsed: result.data.memory_used, connectorsUsed: result.data.connectors_used,
    };
    setMsgs((messages) => [...messages.map((message) => message.id === id ? { ...message, status: undefined } : message), assistant]);
    if (result.data.proposed_actions[0]) setSelectedActionId(result.data.proposed_actions[0].action_id);
    setValidation(null);
    setValidationFailure(null);
  }

  function send() {
    const text = draft.trim();
    if (!text || busy || !enabled) return;
    const id = crypto.randomUUID();
    setMsgs((messages) => [...messages, { id, role: 'user', text }]);
    setDraft('');
    void deliver(id, text);
  }

  async function validateProposal(action: ProposedAction) {
    if (validating) return;
    setValidating(true);
    setValidation(null);
    setValidationFailure(null);
    const result = await api.validateAction(action);
    setValidating(false);
    if (!result.ok) { setValidationFailure(result); return; }
    setValidation(result.data);
  }

  function inspectValidation(action: ProposedAction) {
    const check = api.recentPolicyChecks().find((entry) => entry.action.action_id === action.action_id);
    if (check) setInspect(check);
  }

  return (
    <div className="page chat">
      <PageHeader title="Chat workbench" sub="Conversation and policy review stay separate. A proposal is never executed here." />
      {!enabled && <Banner tone="warn" title="Chat isn't available yet">The live API does not register <code>/api/v1/chat</code>. No message is sent in live mode.</Banner>}
      <div className="chat-workbench">
        <section className="panel chat-conversation" aria-label="Conversation workbench">
          <header><div><span className="eyebrow">CONVERSATION</span><h2>Assistant stream</h2></div><span className="scenario-indicator">{api.mode === 'mock' ? 'SANDBOX' : 'LIVE'}</span></header>
          <div className="log" role="log" aria-live="polite" aria-label="Conversation">
            {msgs.length === 0 && <Empty title="Start a conversation">{enabled ? 'Ask a question or try “delete old note_001” to see a policy proposal.' : 'Conversation will be available when the backend registers chat.'}</Empty>}
            {msgs.map((message) => (
              <article key={message.id} className={`msg ${message.role}`}>
                <div className="who">{message.role === 'user' ? 'YOU' : 'CORTEXSTONE'}</div>
                {message.text && <div className="bubble">{message.text}</div>}
                {message.status === 'failed' && <Banner tone="bad" title="Message not delivered">{message.error} <button className="btn" onClick={() => void deliver(message.id, message.text)} disabled={busy}><RefreshCw size={14} />Retry</button></Banner>}
                {message.role === 'assistant' && (
                  <footer className="provenance-footer">
                    <span>model · {message.model ?? (api.mode === 'mock' ? 'sandbox-model' : 'not reported')}</span>
                    <span>memory · {message.memoryUsed?.length ? message.memoryUsed.join(', ') : 'not reported'}</span>
                    <span>connectors · {message.connectorsUsed?.length ? message.connectorsUsed.join(', ') : 'not reported'}</span>
                  </footer>
                )}
              </article>
            ))}
            {busy && <div className="msg assistant" aria-label="Cortexstone is replying"><div className="typing" aria-hidden><i /><i /><i /></div><span className="sr">Cortexstone is replying</span></div>}
            <div ref={end} />
          </div>
          <div className="composer">
            <label htmlFor="msg" className="sr">Message</label>
            <textarea id="msg" rows={1} value={draft} disabled={!enabled} maxLength={10000} placeholder={enabled ? 'Ask a question or propose an action…' : 'Chat is unavailable'}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } }} />
            <button className="btn primary" onClick={send} disabled={!enabled || busy || !draft.trim()} aria-label="Send message"><Send size={15} />Send</button>
          </div>
          <div className="chat-shortcut">ENTER TO SEND <kbd>SHIFT + ENTER</kbd> NEW LINE</div>
        </section>

        <aside className="panel chat-dock" aria-label="Policy and action dock">
          <header><div><span className="eyebrow">POLICY DOCK</span><h2>Proposed actions</h2></div><Badge tone="info">VALIDATE ONLY</Badge></header>
          <p className="dock-disclaimer">Policy Check Only (Does Not Execute)</p>
          {actions.length === 0 ? <Empty title="No proposals yet" >Assistant proposals appear here, separate from conversation text.</Empty> : actions.map((action) => (
            <section className="dock-proposal" key={action.action_id} aria-current={selectedAction?.action_id === action.action_id}>
              <div className="dock-proposal-head"><code>{action.tool_name}</code><button className="btn icon" onClick={() => inspectValidation(action)} aria-label={`Inspect ${action.tool_name} response JSON`}><FileJson2 size={14} /></button></div>
              <div className="muted">Target · {action.target_ref}</div>
              {action.purpose && <div className="muted">{action.purpose}</div>}
              <div className="dock-actions">
                <button className="btn primary" onClick={() => { setSelectedActionId(action.action_id); void validateProposal(action); }} disabled={validating}><ShieldCheck size={13} />{validating ? 'Checking…' : 'Check policy'}</button>
                <button className="btn" onClick={() => { setSelectedActionId(action.action_id); setValidation(null); setValidationFailure(null); }}>Select</button>
              </div>
              {selectedAction?.action_id === action.action_id && validation && <div className={`dock-result ${validation.status}`}><strong>{validation.status.replace('_', ' ')}</strong><span>{validation.reason.replaceAll('_', ' ')}</span><button className="text-link" onClick={() => inspectValidation(action)}>Inspect response</button></div>}
              {selectedAction?.action_id === action.action_id && validationFailure && <p className="dock-error">{validationFailure.message}</p>}
            </section>
          ))}
          <div className="dock-footer"><ShieldCheck size={14} /><span>Validation cannot approve, schedule, or run a proposal.</span></div>
        </aside>
      </div>
      <Modal open={inspect !== null} title="Policy validation response" onClose={() => setInspect(null)}>
        {inspect && <><p className="modal-intro muted">Raw response is displayed as text. This is not execution.</p><pre>{JSON.stringify({ action: inspect.action, validation: inspect.result, validated_at: inspect.at }, null, 2)}</pre></>}
      </Modal>
    </div>
  );
}
