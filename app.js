const toolContent = {
  move: { label: 'START HERE · 5 MINUTES', title: 'Step outside, no destination needed.', text: "Walk until you can spot three things further away than your screen. The aim isn't productivity; it's giving your attention a wider frame.", action: 'Begin reset', toast: 'Your 5-minute outside reset is ready. You deserve the air.' },
  reset: { label: 'QUICK RESET · 90 SECONDS', title: 'Let your system come down a notch.', text: 'Relax your jaw. Drop your shoulders. Breathe out a little longer than you breathe in, six times. This is not a test to pass.', action: 'Start 90 seconds', toast: 'A 90-second downshift has started. No need to do it perfectly.' },
  sort: { label: 'CLEAR THE CLUTTER · 3 MINUTES', title: 'Name one next move, not every move.', text: 'Write the task that matters most. Under it, add the smallest action that could make it less vague. Stop there.', action: 'Open a tiny plan', toast: 'Your tiny-plan space is open. One next move is enough.' },
  refuel: { label: 'BASIC NEEDS · 10 MINUTES', title: 'Fuel is a study strategy.', text: 'Take water and something with actual substance. Your brain does not need to earn this - it is part of doing demanding work.', action: 'Set a refuel cue', toast: 'A 10-minute refuel cue is set. Future-you will be glad.' }
};

const modalBackdrop = document.querySelector('#modalBackdrop');
const modalContent = document.querySelector('#modalContent');
let selectedDuration = 15;
let interactionMonitor;

const apiSession = {
  token: sessionStorage.getItem('equilibrium-api-session') || '',
  account: null
};

async function apiRequest(path, options = {}) {
  const headers = { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) };
  if (apiSession.token) headers.Authorization = `Bearer ${apiSession.token}`;
  let response;
  try { response = await fetch(path, { ...options, headers }); } catch (_) { throw new Error('The local Equilibrium service is unavailable. Start server.py to use this feature.'); }
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : {};
  if (!response.ok) throw new Error(payload.error || 'This request could not be completed.');
  return payload;
}

function setApiSession(token, account) {
  apiSession.token = token || '';
  apiSession.account = account || null;
  if (token) sessionStorage.setItem('equilibrium-api-session', token);
  else sessionStorage.removeItem('equilibrium-api-session');
}

async function scheduleDeviceNudge(minutes) {
  const message = `Your ${minutes}-minute focus block is complete. Choose a small reset that fits your energy.`;
  if (!('Notification' in window)) {
    window.setTimeout(() => showToast(message), minutes * 60_000);
    return 'This browser does not support device notifications. Equilibrium will show an in-app reminder while it stays open.';
  }
  let permission = Notification.permission;
  if (permission === 'default') permission = await Notification.requestPermission();
  window.setTimeout(() => {
    if (Notification.permission === 'granted') new Notification('Equilibrium · gentle nudge', { body: message });
    else showToast(message);
  }, minutes * 60_000);
  return permission === 'granted' ? 'Device notification scheduled. Keep this browser available for the reminder.' : 'Notification permission was not granted, so Equilibrium will show an in-app reminder if it remains open.';
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function coefficientOfVariation(values) {
  if (values.length < 2) return 0;
  const average = values.reduce((total, value) => total + value, 0) / values.length;
  const variance = values.reduce((total, value) => total + (value - average) ** 2, 0) / values.length;
  return average ? Math.sqrt(variance) / average : 0;
}

function createInteractionMonitor() {
  const storageKey = 'equilibrium-private-interaction-baseline-v1';
  const trainingKey = 'equilibrium-private-cadence-checkins-v1';
  const trialHistoryKey = 'equilibrium-private-cadence-trials-v1';
  const typingToggle = document.querySelector('#typingToggle');
  const scrollToggle = document.querySelector('#scrollToggle');
  const nodes = {
    typingStatus: document.querySelector('#typingStatus'), typingNote: document.querySelector('#typingNote'), typingTrend: document.querySelector('#typingTrend'),
    scrollStatus: document.querySelector('#scrollStatus'), scrollNote: document.querySelector('#scrollNote'), scrollTrend: document.querySelector('#scrollTrend'),
    typingSample: document.querySelector('#typingSample'), typingMetric: document.querySelector('#typingMetric'),
    scrollSample: document.querySelector('#scrollSample'), scrollMetric: document.querySelector('#scrollMetric')
  };
  const state = { intervals: [], keyEvents: [], scrollEvents: [], trainingSamples: [], trialHistory: [], trial: null, lastKeyAt: 0, lastScrollAt: 0, lastScrollY: window.scrollY, lastDirection: 0, typingBaseline: null, scrollBaseline: null };
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey));
    state.typingBaseline = stored?.typingBaseline || null;
    state.scrollBaseline = stored?.scrollBaseline || null;
    state.trainingSamples = JSON.parse(localStorage.getItem(trainingKey)) || [];
    state.trialHistory = JSON.parse(localStorage.getItem(trialHistoryKey)) || [];
  } catch (_) { /* Keep aggregates in memory if local storage is unavailable. */ }

  const saveBaseline = () => {
    try { localStorage.setItem(storageKey, JSON.stringify({ typingBaseline: state.typingBaseline, scrollBaseline: state.scrollBaseline })); } catch (_) { /* On-device storage is optional. */ }
  };
  const saveTrainingSamples = () => {
    try { localStorage.setItem(trainingKey, JSON.stringify(state.trainingSamples)); } catch (_) { /* On-device storage is optional. */ }
  };
  const saveTrialHistory = () => {
    try { localStorage.setItem(trialHistoryKey, JSON.stringify(state.trialHistory)); } catch (_) { /* On-device storage is optional. */ }
  };
  const recent = (list, limit) => list.slice(-limit);
  const setTyping = (status, note, trend, metric) => {
    nodes.typingStatus.textContent = status; nodes.typingNote.textContent = note; nodes.typingTrend.textContent = trend;
    nodes.typingSample.textContent = `${state.intervals.length} timing events`;
    nodes.typingMetric.textContent = metric;
  };
  const setScroll = (status, note, trend, metric) => {
    nodes.scrollStatus.textContent = status; nodes.scrollNote.textContent = note; nodes.scrollTrend.textContent = trend;
    nodes.scrollSample.textContent = `${state.scrollEvents.length} movements`;
    nodes.scrollMetric.textContent = metric;
  };
  const resetVisuals = () => {
    setTyping('Learning baseline', 'No text is read or stored', '↗', 'Learning a baseline');
    setScroll('Waiting for activity', 'Never used as a stress label', '—', 'Waiting for activity');
  };
  const refreshTyping = () => {
    if (!typingToggle.checked) return setTyping('Off', 'Typing cadence is disabled', '—', 'Disabled by you');
    const intervals = recent(state.intervals, 120);
    const events = recent(state.keyEvents, 120);
    if (!state.typingBaseline || intervals.length < 40) {
      return setTyping('Learning baseline', `${intervals.length} of 120 timing events`, '↗', 'Learning a baseline');
    }
    const currentMedian = median(intervals);
    const currentVariation = coefficientOfVariation(intervals);
    const currentCorrectionRate = events.filter(Boolean).length / Math.max(events.length, 1);
    const flags = [currentMedian > state.typingBaseline.median * 1.35, currentVariation > state.typingBaseline.variation * 1.45 + .05, currentCorrectionRate > state.typingBaseline.corrections * 1.6 + .03].filter(Boolean).length;
    if (flags >= 2) return setTyping('Pattern changed', 'Pace and corrections differ from your usual range', '↑', 'Consider a reset if it persists');
    if (flags === 1) return setTyping('Small change', 'One timing pattern is outside your usual range', '↗', 'Check again after your next task');
    return setTyping('In your range', 'Timing looks close to your own baseline', '—', 'No action suggested');
  };
  const refreshScroll = () => {
    if (!scrollToggle.checked) return setScroll('Off', 'Scrolling patterns are disabled', '—', 'Disabled by you');
    const events = recent(state.scrollEvents, 80);
    if (!state.scrollBaseline || events.length < 12) return setScroll('Waiting for activity', `${events.length} of 40 movements`, '—', 'Not enough context yet');
    const reversals = events.filter(event => event.reversed).length / events.length;
    const span = Math.max(1, (events.at(-1).at - events[0].at) / 60000);
    const rate = events.length / span;
    const unusual = events.length >= 12 && reversals > Math.max(.42, state.scrollBaseline.reversals * 1.6) && rate > Math.max(10, state.scrollBaseline.rate * 1.4);
    if (unusual) return setScroll('Frequent reversals', 'May be active reading or navigation friction', '↕', 'Never used alone for a nudge');
    if (reversals > .3) return setScroll('Backtracking', 'Rereading can be useful - no action suggested', '↕', 'Context matters');
    return setScroll('In your range', 'Scrolling is close to your normal pattern', '—', 'Never a stress score');
  };
  const setTypingBaseline = () => {
    if (state.typingBaseline || state.intervals.length < 120) return;
    const intervals = recent(state.intervals, 120);
    const events = recent(state.keyEvents, 120);
    state.typingBaseline = { median: median(intervals), variation: coefficientOfVariation(intervals), corrections: events.filter(Boolean).length / Math.max(events.length, 1) };
    saveBaseline();
  };
  const setScrollBaseline = () => {
    if (state.scrollBaseline || state.scrollEvents.length < 40) return;
    const events = recent(state.scrollEvents, 40);
    const reversals = events.filter(event => event.reversed).length / events.length;
    const span = Math.max(1, (events.at(-1).at - events[0].at) / 60000);
    state.scrollBaseline = { reversals, rate: events.length / span };
    saveBaseline();
  };
  const recordTrialTiming = (at, isCorrection = false) => {
    if (!state.trial?.active) return;
    if (state.lastKeyAt) {
      const interval = at - state.lastKeyAt;
      if (interval >= 35 && interval <= 3000) state.trial.intervals = recent([...state.trial.intervals, interval], 180);
    }
    state.trial.keyEvents = recent([...state.trial.keyEvents, isCorrection], 180);
    state.lastKeyAt = at;
  };
  const observeKey = event => {
    if (!typingToggle.checked || !state.trial?.active || event.target.id !== 'typingTrialText' || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
    const isMeasuredKey = event.key.length === 1 || event.key === 'Backspace' || event.key === 'Enter' || event.key === 'Spacebar';
    if (!isMeasuredKey) return;
    recordTrialTiming(Date.now(), event.key === 'Backspace');
  };
  const observeTrialInput = event => {
    if (!typingToggle.checked || !state.trial?.active || event.target.id !== 'typingTrialText' || event.isComposing) return;
    // Assistive and alternate entry can emit input without a preceding keydown; no text is read here.
    if (state.lastKeyAt && Date.now() - state.lastKeyAt < 32) return;
    recordTrialTiming(Date.now(), event.inputType === 'deleteContentBackward');
  };
  const observeScroll = () => {
    if (!scrollToggle.checked || !document.querySelector('#loginGate').classList.contains('is-leaving')) return;
    const now = Date.now(); const currentY = window.scrollY; const delta = currentY - state.lastScrollY;
    if (Math.abs(delta) < 12) return;
    const direction = Math.sign(delta);
    const reversed = state.lastDirection && direction !== state.lastDirection && now - state.lastScrollAt < 1200;
    state.scrollEvents = recent([...state.scrollEvents, { at: now, reversed }], 120);
    state.lastScrollAt = now; state.lastScrollY = currentY; state.lastDirection = direction;
    setScrollBaseline(); refreshScroll();
  };
  const clear = () => {
    state.intervals = []; state.keyEvents = []; state.scrollEvents = []; state.trainingSamples = []; state.trialHistory = []; state.trial = null; state.lastKeyAt = 0; state.lastScrollAt = 0; state.lastDirection = 0; state.typingBaseline = null; state.scrollBaseline = null;
    try { localStorage.removeItem(storageKey); localStorage.removeItem(trainingKey); localStorage.removeItem(trialHistoryKey); } catch (_) { /* Nothing else to clear. */ }
    resetVisuals();
  };
  const captureCheckIn = label => {
    const intervals = recent(state.intervals, 120);
    const events = recent(state.keyEvents, 120);
    if (intervals.length < 40) return { ok: false, message: `Keep typing a little longer - ${intervals.length} of 40 timing events collected.` };
    const features = [median(intervals) / 1000, coefficientOfVariation(intervals), events.filter(Boolean).length / Math.max(events.length, 1), intervals.filter(interval => interval > 800).length / intervals.length];
    state.trainingSamples = recent([...state.trainingSamples, { label, features }], 360);
    saveTrainingSamples();
    return { ok: true, count: state.trainingSamples.length };
  };
  const getTrialSummary = () => {
    const intervals = state.trial?.intervals || [];
    const events = state.trial?.keyEvents || [];
    return { timingEvents: intervals.length, medianMs: intervals.length ? Math.round(median(intervals)) : 0, variability: intervals.length ? Math.round(coefficientOfVariation(intervals) * 100) : 0, corrections: events.filter(Boolean).length, longPauses: intervals.filter(interval => interval > 800).length };
  };
  const startTrial = () => {
    state.trial = { active: true, intervals: [], keyEvents: [] };
    state.lastKeyAt = 0;
    return getTrialSummary();
  };
  const finishTrial = () => {
    const summary = getTrialSummary();
    state.trial.active = false;
    if (summary.timingEvents < 10) return { ok: false, message: 'Type a little more before saving the trial.', summary };
    state.intervals = recent([...state.intervals, ...state.trial.intervals], 180);
    state.keyEvents = recent([...state.keyEvents, ...state.trial.keyEvents], 180);
    state.trialHistory = recent([...state.trialHistory, summary], 12);
    state.trial = null;
    setTypingBaseline(); refreshTyping(); saveTrialHistory();
    return { ok: true, summary, history: state.trialHistory };
  };
  const cancelTrial = () => { state.trial = null; state.lastKeyAt = 0; };
  document.addEventListener('keydown', observeKey, true);
  document.addEventListener('input', observeTrialInput, true);
  window.addEventListener('scroll', observeScroll, { passive: true });
  typingToggle.addEventListener('change', refreshTyping);
  scrollToggle.addEventListener('change', refreshScroll);
  resetVisuals(); refreshTyping(); refreshScroll();
  return { clear, captureCheckIn, getTrainingSamples: () => state.trainingSamples.map(sample => ({ label: sample.label, features: [...sample.features] })), startTrial, getTrialSummary, finishTrial, cancelTrial, getTrialHistory: () => state.trialHistory.map(item => ({ ...item })) };
}

function showToast(message) {
  const toast = document.querySelector('#toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => toast.classList.remove('show'), 3400);
}

function openModal(content) {
  modalContent.innerHTML = content;
  modalBackdrop.classList.add('open');
  modalBackdrop.setAttribute('aria-hidden', 'false');
}

function closeModal() {
  interactionMonitor?.cancelTrial?.();
  modalBackdrop.classList.remove('open');
  modalBackdrop.setAttribute('aria-hidden', 'true');
}

function resetModal() {
  openModal(`
    <p class="eyebrow">A PAUSE, ON YOUR TERMS</p>
    <h2>When should we tap you on the shoulder?</h2>
    <p>We'll send one quiet nudge, right when your current focus block is likely to be ending. No guilt if you ignore it.</p>
    <div class="choice-list" id="durationChoices">
      <button class="active" data-minutes="15"><b>In 15 minutes</b><small>Finish this thought, then make room.</small></button>
      <button data-minutes="25"><b>In 25 minutes</b><small>One more focused sprint first.</small></button>
      <button data-minutes="45"><b>In 45 minutes</b><small>Keep a longer block, with a safety rail.</small></button>
    </div>
    <div class="modal-actions"><button class="primary-button" id="confirmReset">Schedule a gentle nudge <span>→</span></button><button class="secondary-button" id="cancelReset">Maybe later</button></div>
  `);
  document.querySelectorAll('#durationChoices button').forEach(button => button.addEventListener('click', () => {
    selectedDuration = Number(button.dataset.minutes);
    document.querySelectorAll('#durationChoices button').forEach(item => item.classList.toggle('active', item === button));
  }));
  document.querySelector('#confirmReset').addEventListener('click', async () => {
    closeModal();
    const result = await scheduleDeviceNudge(selectedDuration);
    showToast(result);
  });
  document.querySelector('#cancelReset').addEventListener('click', closeModal);
}

function supportModal() {
  openModal(`
    <p class="eyebrow">REAL PEOPLE, REAL OPTIONS</p>
    <h2>Support can be a practical next step.</h2>
    <p>You choose what feels right. Equilibrium never contacts anyone for you or shares your signals without a clear action from you.</p>
    <div class="support-options">
      <div class="support-option"><span>◌</span><div><b>Talk to someone you trust</b><br />A low-pressure message can be enough to start.</div></div>
      <div class="support-option"><span>♡</span><div><b>Find campus wellbeing support</b><br />See appointment and drop-in options.</div></div>
      <div class="support-option"><span>⌁</span><div><b>Get urgent help now</b><br />Use your local emergency or crisis service.</div></div>
    </div>
    <div class="modal-actions"><button class="primary-button" id="supportDone">Got it</button></div>
  `);
  document.querySelector('#supportDone').addEventListener('click', closeModal);
}

function guideModal() {
  openModal(`
    <p class="eyebrow">A SIMPLE START</p>
    <h2>How Equilibrium works</h2>
    <p>Use it as a private study companion, not a measure of your worth or a mental-health diagnosis.</p>
    <div class="support-options">
      <div class="support-option"><span>01</span><div><b>Notice your rhythm</b><br />Today shows optional, on-device patterns such as pauses and task switching.</div></div>
      <div class="support-option"><span>02</span><div><b>Choose a reset</b><br />Accept, postpone, or ignore a nudge. Then pick a small strategy that fits.</div></div>
      <div class="support-option"><span>03</span><div><b>Unload or connect</b><br />Keep a private note, browse peer reminders, or choose real-world support.</div></div>
      <div class="support-option"><span>04</span><div><b>Stay in control</b><br />Turn signals off, delete the local baseline, or log out whenever you want.</div></div>
    </div>
    <div class="modal-actions"><button class="primary-button" id="guideDone">I'm ready</button></div>
  `);
  document.querySelector('#guideDone').addEventListener('click', closeModal);
}

function peerModal() {
  openModal(`
    <p class="eyebrow">PEER SPACE</p>
    <h2>Connection without comparison.</h2>
    <p>Read anonymous, moderated student reminders. This space is for affirmation and shared coping strategies - not crisis support or clinical advice.</p>
    <div class="support-options"><div class="support-option"><span>♡</span><div><b>Choose a topic</b><br />Deadlines, sleep, meals, asking for help, or boundaries.</div></div><div class="support-option"><span>⌑</span><div><b>Share anonymously</b><br />Remove identifiers before posting. You control every word.</div></div></div>
    <div class="modal-actions"><button class="primary-button" id="peerDone">Browse reminders</button></div>
  `);
  document.querySelector('#peerDone').addEventListener('click', () => { closeModal(); showToast('Peer Space is a moderated prototype in this build.'); });
}

function summaryModal() {
  openModal(`
    <p class="eyebrow">PRIVATE SUMMARY</p>
    <h2>Share context, not surveillance.</h2>
    <p>In a live service, you could choose a short summary of your own selected patterns and notes. No raw typing, browsing, or background data would be included.</p>
    <div class="data-empty">Preview before sharing: “I’ve had several long study blocks this week and would like help planning sustainable breaks.”</div>
    <div class="modal-actions"><button class="primary-button" id="summaryDone">Keep it private</button></div>
  `);
  document.querySelector('#summaryDone').addEventListener('click', closeModal);
}

function renderTrialHistory() {
  const historyNode = document.querySelector('#trialHistory');
  if (!historyNode || !interactionMonitor) return;
  const history = interactionMonitor.getTrialHistory().slice(-4).reverse();
  if (!history.length) {
    historyNode.innerHTML = '<span>No private trials saved on this device yet.</span>';
    return;
  }
  historyNode.innerHTML = history.map((trial, index) => `<div class="trial-history-row"><b>Trial ${history.length - index}</b><span>${trial.timingEvents} events</span><span>${trial.medianMs} ms median</span><span>${trial.corrections} corrections</span></div>`).join('');
}

function typingTrialModal() {
  interactionMonitor.startTrial();
  openModal(`
    <div class="trial-dialog">
      <p class="eyebrow">PRIVATE TRIAL USAGE</p>
      <h2>Try a real task. See only your cadence summary.</h2>
      <p>Write a task plan, draft a study note, or use the prompt below. The text remains in this pop-up and is discarded when you finish. Equilibrium records only timing aggregates for the trial.</p>
      <textarea id="typingTrialText" class="trial-textarea" placeholder="Example: Break my assignment into three next steps, then write the first sentence I will start with..."></textarea>
      <div class="trial-live"><div><span>TIMING EVENTS</span><b id="trialEventCount">0</b></div><div><span>MEDIAN PACE</span><b id="trialMedian">--</b></div><div><span>VARIABILITY</span><b id="trialVariation">--</b></div><div><span>CORRECTIONS</span><b id="trialCorrections">0</b></div></div>
      <div class="trial-privacy"><b>Saved if you choose:</b> event count, median timing, variability, correction count and long-pause count. No text, keys, screenshots, URLs or browsing history.</div>
      <div class="modal-actions"><button class="primary-button" id="finishTypingTrial">Save private trial <span>→</span></button><button class="secondary-button" id="discardTypingTrial">Discard</button></div>
      <p class="login-feedback" id="trialFeedback" role="status" aria-live="polite"></p>
    </div>
  `);
  const updateTrialView = () => {
    const summary = interactionMonitor.getTrialSummary();
    document.querySelector('#trialEventCount').textContent = summary.timingEvents;
    document.querySelector('#trialMedian').textContent = summary.medianMs ? `${summary.medianMs} ms` : '--';
    document.querySelector('#trialVariation').textContent = summary.timingEvents ? `${summary.variability}%` : '--';
    document.querySelector('#trialCorrections').textContent = summary.corrections;
  };
  const trialText = document.querySelector('#typingTrialText');
  trialText.addEventListener('input', updateTrialView);
  trialText.focus();
  document.querySelector('#finishTypingTrial').addEventListener('click', () => {
    const result = interactionMonitor.finishTrial();
    if (!result.ok) {
      document.querySelector('#trialFeedback').textContent = result.message;
      return;
    }
    renderTrialHistory();
    closeModal();
    showToast(`Private trial saved: ${result.summary.timingEvents} timing events. No text was stored.`);
  });
  document.querySelector('#discardTypingTrial').addEventListener('click', () => {
    closeModal();
    showToast('Typing trial discarded. No trial summary was saved.');
  });
}

function dataModal() {
  openModal(`
    <p class="eyebrow">LOCAL DATA CONTROL</p>
    <h2>Your baseline belongs to you.</h2>
    <p>Equilibrium keeps a small local aggregate baseline on this device so it can compare today to your usual rhythm. It contains summary values, not typed text or scrolling history, and you can remove it whenever you want.</p>
    <div class="data-empty" id="deleteStatus">No data has been shared with a university, counsellor, or third party.</div>
    <div class="modal-actions"><button class="primary-button" id="exportData">Export a copy</button><button class="secondary-button" id="deleteData">Delete local baseline</button></div>
  `);
  document.querySelector('#exportData').addEventListener('click', () => showToast('A private summary would be prepared here - raw signals are never included.'));
  document.querySelector('#deleteData').addEventListener('click', () => {
    interactionMonitor?.clear();
    window.EquilibriumLSTM?.clear();
    document.querySelector('#deleteStatus').textContent = 'Local baseline deleted in this prototype. Equilibrium would need a new opt-in learning period.';
    showToast('Local baseline removed. You remain in control.');
  });
}

function informationModal(title, body) {
  openModal(`<p class="eyebrow">A LITTLE CONTEXT</p><h2>${title}</h2><p>${body}</p><div class="modal-actions"><button class="primary-button" id="infoDone">Got it</button></div>`);
  document.querySelector('#infoDone').addEventListener('click', closeModal);
}

function bindTools() {
  document.querySelectorAll('.tool-card').forEach(card => card.addEventListener('click', () => {
    const item = toolContent[card.dataset.tool];
    document.querySelectorAll('.tool-card').forEach(tool => tool.classList.toggle('selected-tool', tool === card));
    const detail = document.querySelector('#toolDetail');
    detail.querySelector('.eyebrow').textContent = item.label;
    detail.querySelector('h3').textContent = item.title;
    detail.querySelector('p:not(.eyebrow)').textContent = item.text;
    detail.querySelector('#beginTool').innerHTML = `${item.action} <span>→</span>`;
    detail.dataset.toast = item.toast;
  }));
  document.querySelector('#beginTool').addEventListener('click', () => showToast(document.querySelector('#toolDetail').dataset.toast || toolContent.move.toast));
}

function selectView(view) {
  document.querySelectorAll('[data-view]').forEach(section => section.classList.toggle('is-hidden', section.dataset.view !== view));
  document.querySelectorAll('[data-view-link]').forEach(link => link.classList.toggle('active', link.dataset.viewLink === view));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderCommunityPosts(posts) {
  const target = document.querySelector('#communityPosts');
  if (!target) return;
  target.replaceChildren();
  if (!posts.length) {
    const empty = document.createElement('p');
    empty.className = 'data-empty';
    empty.textContent = 'No notes yet. A small, practical reminder can be the first one.';
    target.append(empty);
    return;
  }
  const topics = { deadlines: 'Deadlines', sleep: 'Sleep & recovery', meals: 'Meals & energy', boundaries: 'Boundaries', asking_for_help: 'Asking for help' };
  posts.forEach(post => {
    const card = document.createElement('article'); card.className = 'community-post';
    const header = document.createElement('header');
    const topic = document.createElement('span'); topic.textContent = topics[post.topic] || 'Student note';
    const date = document.createElement('span'); date.textContent = new Date(post.created_at).toLocaleDateString();
    const text = document.createElement('p'); text.textContent = post.body;
    header.append(topic, date); card.append(header, text); target.append(card);
  });
}

async function loadCommunity() {
  const status = document.querySelector('#communityStatus');
  try {
    const data = await apiRequest('/api/community/posts');
    renderCommunityPosts(data.posts || []);
  } catch (error) {
    status.textContent = error.message;
  }
}

function reflectionResultModal(answer) {
  openModal('<p class="eyebrow">PRIVATE REFLECTION</p><h2>A calmer way forward.</h2><div class="data-empty" id="reflectionAnswer"></div><div class="modal-actions"><button class="primary-button" id="reflectionDone">Keep this private</button></div>');
  document.querySelector('#reflectionAnswer').textContent = answer;
  document.querySelector('#reflectionDone').addEventListener('click', closeModal);
}

const FIREBASE_WEB_SDK_VERSION = '12.1.0';
let firebaseMessaging;

function deviceReminderControls() {
  return {
    toggle: document.querySelector('#deviceReminderToggle'),
    note: document.querySelector('#deviceReminderNote'),
    settings: document.querySelector('#deviceReminderSettings')
  };
}

async function refreshDeviceReminderControls() {
  const { toggle, note, settings } = deviceReminderControls();
  if (!apiSession.token) {
    toggle.checked = false; toggle.disabled = true; settings.disabled = true;
    note.textContent = 'Sign in to check whether secure notifications are available.';
    return;
  }
  try {
    const [integrations, preferenceResult] = await Promise.all([
      apiRequest('/api/integrations/status'),
      apiRequest('/api/integrations/notifications/preference')
    ]);
    const ready = integrations.notifications?.fcmRegistrationReady && window.isSecureContext;
    const preference = preferenceResult.preference || {};
    toggle.checked = Boolean(preference.fcm_enabled);
    toggle.disabled = !ready;
    settings.disabled = !ready;
    if (!window.isSecureContext) note.textContent = 'Background reminders require the live HTTPS version of Equilibrium.';
    else if (!integrations.notifications?.fcmConfigured) note.textContent = 'Background reminders will appear here after the approved Firebase setup.';
    else if (!integrations.notifications?.fcmRegistrationReady) note.textContent = 'Notifications are configured, but encrypted device storage is not ready yet.';
    else note.textContent = preference.fcm_enabled ? 'Enabled by you. You can switch this off or set quiet hours anytime.' : 'Optional. Reminders are never triggered from a stress score.';
  } catch (_) {
    toggle.disabled = true; settings.disabled = true;
    note.textContent = 'Background reminders are unavailable while the local service is offline.';
  }
}

async function enableFcmReminders() {
  if (!window.isSecureContext || !('serviceWorker' in navigator) || !('Notification' in window)) {
    throw new Error('Background reminders need a supported browser and the HTTPS version of Equilibrium.');
  }
  const permission = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
  if (permission !== 'granted') throw new Error('Notifications remain off because browser permission was not granted.');
  const config = await apiRequest('/api/integrations/firebase-config');
  const [firebaseApp, firebaseMessagingModule] = await Promise.all([
    import(`https://www.gstatic.com/firebasejs/${FIREBASE_WEB_SDK_VERSION}/firebase-app.js`),
    import(`https://www.gstatic.com/firebasejs/${FIREBASE_WEB_SDK_VERSION}/firebase-messaging.js`)
  ]);
  const app = firebaseApp.getApps().length ? firebaseApp.getApp() : firebaseApp.initializeApp(config);
  firebaseMessaging = firebaseMessagingModule.getMessaging(app);
  const registration = await navigator.serviceWorker.register('/firebase-messaging-sw.js', { type: 'module' });
  const registrationToken = await firebaseMessagingModule.getToken(firebaseMessaging, { vapidKey: config.vapidKey, serviceWorkerRegistration: registration });
  if (!registrationToken) throw new Error('Firebase did not return a device registration token.');
  await apiRequest('/api/integrations/fcm/registrations', { method: 'POST', body: JSON.stringify({ registrationToken, pushConsent: true }) });
  await apiRequest('/api/integrations/notifications/preference', { method: 'POST', body: JSON.stringify({ enabled: true, quietStart: null, quietEnd: null, timezoneOffsetMinutes: new Date().getTimezoneOffset() }) });
}

function deviceReminderSettingsModal() {
  openModal('<p class="eyebrow">BACKGROUND REMINDERS</p><h2>Choose quieter hours.</h2><p>Equilibrium will not send a background nudge during these hours. Leave both fields blank if you do not want a quiet period.</p><div class="quiet-hours"><label>Start <input id="quietStart" type="time" /></label><label>End <input id="quietEnd" type="time" /></label></div><div class="modal-actions"><button class="primary-button" id="saveQuietHours">Save quiet hours</button></div>');
  apiRequest('/api/integrations/notifications/preference').then(result => {
    document.querySelector('#quietStart').value = result.preference?.quiet_start || '';
    document.querySelector('#quietEnd').value = result.preference?.quiet_end || '';
  }).catch(() => {});
  document.querySelector('#saveQuietHours').addEventListener('click', async () => {
    const { toggle } = deviceReminderControls();
    try {
        await apiRequest('/api/integrations/notifications/preference', {
          method: 'POST',
          body: JSON.stringify({ enabled: toggle.checked, quietStart: document.querySelector('#quietStart').value || null, quietEnd: document.querySelector('#quietEnd').value || null, timezoneOffsetMinutes: new Date().getTimezoneOffset() })
      });
      closeModal();
      showToast('Quiet hours saved. You can change them anytime.');
    } catch (error) { showToast(error.message); }
  });
}

function init() {
  const ANU_EMAIL = 'anu@equilibrium.student';
  const ANU_PASSWORD = 'Anu@Equilibrium26';
  const loginGate = document.querySelector('#loginGate');
  const passwordField = document.querySelector('#studentPassword');
  const loginFeedback = document.querySelector('#loginFeedback');
  const setLoginFeedback = message => { loginFeedback.textContent = message; };
  document.querySelector('#loginForm').addEventListener('submit', async event => {
    event.preventDefault();
    const email = document.querySelector('#studentEmail').value.trim().toLowerCase();
    const password = passwordField.value;
    try {
      const session = await apiRequest('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
      setApiSession(session.token, session.account);
    } catch (error) {
      // Keep the requested Anu prototype usable when opened from a basic static server.
      if (email !== ANU_EMAIL || password !== ANU_PASSWORD) {
        setLoginFeedback(error.message.includes('local Equilibrium service') ? 'That email or password does not match Anu\'s account. Please try again.' : error.message);
        passwordField.focus();
        return;
      }
    }
    setLoginFeedback('');
    loginGate.classList.add('is-leaving');
    showToast('Welcome back, Anu. Your private space is ready.');
    refreshDeviceReminderControls();
  });
  document.querySelector('#studentEmail').addEventListener('input', () => setLoginFeedback(''));
  passwordField.addEventListener('input', () => setLoginFeedback(''));
  document.querySelector('#passwordVisibility').addEventListener('click', () => {
    const visible = passwordField.type === 'text';
    passwordField.type = visible ? 'password' : 'text';
    document.querySelector('#passwordVisibility').setAttribute('aria-label', visible ? 'Show password' : 'Hide password');
  });
  document.querySelector('#forgotPassword').addEventListener('click', () => informationModal('Password reset', 'A secure reset link would be sent to Anu\'s student email in the live service.'));
  document.querySelector('#differentAccount').addEventListener('click', () => {
    document.querySelector('#studentEmail').value = '';
    document.querySelector('#studentPassword').value = '';
    document.querySelector('#studentEmail').focus();
    showToast('Enter another student account to continue.');
  });
  document.querySelector('#loginSupport').addEventListener('click', () => informationModal('Account support', 'Campus support can help with access, without viewing your private Equilibrium signals.'));
  document.querySelector('#guideButton').addEventListener('click', guideModal);
  interactionMonitor = createInteractionMonitor();
  refreshDeviceReminderControls();
  selectView('today');
  renderTrialHistory();
  document.querySelector('#startTypingTrial').addEventListener('click', typingTrialModal);
  document.querySelector('#resetInteractionData').addEventListener('click', () => {
    interactionMonitor.clear();
    window.EquilibriumLSTM?.clear();
    renderTrialHistory();
    showToast('Typing and scrolling baseline removed from this device.');
  });
  let selectedCheckIn = 'steady';
  const trainerStatus = document.querySelector('#trainerStatus');
  document.querySelectorAll('.checkin').forEach(button => button.addEventListener('click', () => {
    selectedCheckIn = button.dataset.checkin;
    document.querySelectorAll('.checkin').forEach(item => item.classList.toggle('selected', item === button));
  }));
  document.querySelector('#saveCheckin').addEventListener('click', () => {
    const result = interactionMonitor.captureCheckIn(selectedCheckIn);
    if (!result.ok) {
      trainerStatus.textContent = result.message;
      return;
    }
    trainerStatus.textContent = `Saved ${selectedCheckIn} check-in locally. ${result.count} labelled windows collected.`;
    showToast('Private check-in saved. Nothing was uploaded.');
  });
  document.querySelector('#trainLstm').addEventListener('click', async () => {
    if (!window.EquilibriumLSTM) {
      trainerStatus.textContent = 'The local ML library is unavailable. Check your connection, then try again.';
      return;
    }
    const trainButton = document.querySelector('#trainLstm');
    trainButton.disabled = true;
    try {
      const result = await window.EquilibriumLSTM.train(interactionMonitor.getTrainingSamples(), message => { trainerStatus.textContent = message; });
      trainerStatus.textContent = `Local model trained on ${result.sequenceCount} labelled sequences. Treat results as a pattern check, not a diagnosis.`;
      showToast('Personal cadence model trained locally.');
    } catch (error) {
      trainerStatus.textContent = error.message;
    } finally {
      trainButton.disabled = false;
    }
  });
  document.querySelector('#predictLstm').addEventListener('click', async () => {
    if (!window.EquilibriumLSTM) {
      trainerStatus.textContent = 'The local ML library is unavailable. Check your connection, then try again.';
      return;
    }
    try {
      const result = await window.EquilibriumLSTM.predict(interactionMonitor.getTrainingSamples());
      trainerStatus.textContent = `Latest pattern is closest to “${result.label}” (${Math.round(result.confidence * 100)}% model confidence). This is not a stress diagnosis.`;
    } catch (error) {
      trainerStatus.textContent = error.message;
    }
  });
  document.querySelector('#logoutButton').addEventListener('click', async () => {
    if (apiSession.token) { try { await apiRequest('/api/auth/logout', { method: 'POST' }); } catch (_) { /* Local session still ends. */ } }
    setApiSession('', null);
    closeModal();
    passwordField.value = '';
    document.querySelector('#studentEmail').value = ANU_EMAIL;
    setLoginFeedback('You have been logged out. Enter Anu\'s password to continue.');
    loginGate.classList.remove('is-leaving');
    refreshDeviceReminderControls();
    window.scrollTo(0, 0);
    setTimeout(() => passwordField.focus(), 50);
  });
  bindTools();
  document.querySelector('#scheduleReset').addEventListener('click', resetModal);
  document.querySelector('#skipNudge').addEventListener('click', () => showToast('Okay. No nudge today - you can always set one when it helps.'));
  document.querySelector('#modalClose').addEventListener('click', closeModal);
  modalBackdrop.addEventListener('click', event => { if (event.target === modalBackdrop) closeModal(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeModal(); });
  document.querySelector('#signalInfo').addEventListener('click', () => informationModal('Your signals stay with you.', 'Equilibrium only works with timing patterns such as pauses, rhythm changes and task-switch counts. It does not read your words, files, tabs, messages or browsing history.'));
  document.querySelector('#capacityInfo').addEventListener('click', () => informationModal('Capacity is a soft signal, not a score.', 'It is a private estimate of how sustainable your current pace is, compared with your own baseline. It is never a judgement of effort, ability, or worth.'));
  document.querySelector('#whyThis').addEventListener('click', () => informationModal('Why this view?', 'Your rhythm is a gentle reflection of your own on-device patterns. It helps Equilibrium time a suggestion before friction piles up - not diagnose your mood.'));
  document.querySelector('#manageData').addEventListener('click', dataModal);
  document.querySelector('#supportButton')?.addEventListener('click', supportModal);
  document.querySelector('#counsellorButton')?.addEventListener('click', supportModal);
  document.querySelector('#peerButton')?.addEventListener('click', peerModal);
  document.querySelector('#shareSummaryButton').addEventListener('click', summaryModal);
  document.querySelector('#urgentButton')?.addEventListener('click', () => informationModal('Urgent support', 'If you might hurt yourself or someone else, or cannot stay safe, contact your local emergency number or crisis service now. Equilibrium cannot provide emergency care.'));
  document.querySelectorAll('.affirm-button').forEach(button => button.addEventListener('click', () => {
    const alreadyAffirmed = button.classList.toggle('affirmed');
    const count = Number(button.textContent.match(/\d+/)[0]) + (alreadyAffirmed ? 1 : -1);
    button.textContent = `♡ ${count}`;
  }));
  document.querySelector('#notificationButton').addEventListener('click', async () => {
    if (!('Notification' in window)) { showToast('This browser does not support device notifications.'); return; }
    const permission = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
    showToast(permission === 'granted' ? 'Device notifications are enabled. You can schedule a gentle nudge from Focus.' : 'Notifications are off. You can still use in-app reminders.');
  });
  document.querySelector('#deviceReminderToggle').addEventListener('change', async event => {
    const toggle = event.target;
    if (!toggle.checked) {
      try {
        await apiRequest('/api/integrations/notifications/preference', { method: 'POST', body: JSON.stringify({ enabled: false, quietStart: null, quietEnd: null, timezoneOffsetMinutes: new Date().getTimezoneOffset() }) });
        showToast('Background device reminders are off for this account.');
      } catch (error) {
        toggle.checked = true;
        showToast(error.message);
      }
      refreshDeviceReminderControls();
      return;
    }
    toggle.disabled = true;
    try {
      await enableFcmReminders();
      showToast('Background reminders are enabled. Set quiet hours if you want them.');
    } catch (error) {
      toggle.checked = false;
      try { await apiRequest('/api/integrations/notifications/preference', { method: 'POST', body: JSON.stringify({ enabled: false, quietStart: null, quietEnd: null, timezoneOffsetMinutes: new Date().getTimezoneOffset() }) }); } catch (_) { /* No preference was stored. */ }
      showToast(error.message);
    } finally {
      refreshDeviceReminderControls();
    }
  });
  document.querySelector('#deviceReminderSettings').addEventListener('click', deviceReminderSettingsModal);
  document.querySelectorAll('.day-selector button').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('.day-selector button').forEach(day => day.classList.toggle('selected', day === button));
    showToast(button.textContent === 'Today' ? 'Showing today’s rhythm.' : `${button.textContent} is available as a preview in this prototype.`);
  }));
  document.querySelector('[data-action="plan"]').addEventListener('click', resetModal);
  let selectedLens = 'next_step';
  document.querySelectorAll('.reflection-lens').forEach(button => button.addEventListener('click', () => {
    selectedLens = button.dataset.lens;
    document.querySelectorAll('.reflection-lens').forEach(item => item.classList.toggle('selected', item === button));
  }));
  document.querySelector('#unloadText').addEventListener('input', event => { document.querySelector('#wordCount').textContent = `${event.target.value.length} / 1200`; });
  document.querySelector('#unloadForm').addEventListener('submit', async event => {
    event.preventDefault();
    const text = document.querySelector('#unloadText').value.trim();
    if (!text) return showToast('Start wherever you are. A sentence is enough.');
    const status = document.querySelector('#reflectionStatus');
    if (!document.querySelector('#reflectionConsent').checked) {
      status.textContent = 'Please explicitly choose whether to send this reflection to the AI assistant.';
      return;
    }
    status.textContent = 'Sending your chosen reflection to the assistant…';
    try {
      const result = await apiRequest('/api/reflection', { method: 'POST', body: JSON.stringify({ text, lens: selectedLens, shareWithAssistant: true }) });
      status.textContent = 'Response ready. Your writing was not stored by Equilibrium.';
      reflectionResultModal(result.reflection);
    } catch (error) { status.textContent = error.message; }
  });
  document.querySelector('#communityText').addEventListener('input', event => { document.querySelector('#communityCount').textContent = `${event.target.value.length} / 500`; });
  document.querySelector('#communityForm').addEventListener('submit', async event => {
    event.preventDefault();
    const status = document.querySelector('#communityStatus');
    const body = document.querySelector('#communityText').value.trim();
    if (!body) { status.textContent = 'Write a small practical note before sharing it.'; return; }
    status.textContent = 'Posting anonymously…';
    try {
      await apiRequest('/api/community/posts', { method: 'POST', body: JSON.stringify({ topic: document.querySelector('#communityTopic').value, body }) });
      document.querySelector('#communityText').value = '';
      document.querySelector('#communityCount').textContent = '0 / 500';
      status.textContent = 'Posted anonymously. Thank you for leaving a useful reminder.';
      loadCommunity();
    } catch (error) { status.textContent = error.message; }
  });
  document.querySelector('#refreshCommunity').addEventListener('click', loadCommunity);
  document.querySelectorAll('.switch input:not(#deviceReminderToggle)').forEach(input => input.addEventListener('change', () => {
    const on = [...document.querySelectorAll('.switch input:not(#deviceReminderToggle):checked')].length;
    showToast(`${on} private signal${on === 1 ? '' : 's'} enabled. Your capacity view adapts to your choices.`);
  }));
  document.querySelectorAll('[data-view-link]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    selectView(link.dataset.viewLink);
    if (link.dataset.viewLink === 'community') loadCommunity();
  }));
  document.querySelector('#privacyShortcut').addEventListener('click', event => { event.preventDefault(); selectView('privacy'); });
  document.querySelector('.brand').addEventListener('click', event => { event.preventDefault(); selectView('today'); });
}

init();
