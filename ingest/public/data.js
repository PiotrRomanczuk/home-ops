/* ============================================================
   data.js — baked realistic state for home-ops console.
   Everything joins on `slug`: logs via source='app:<slug>',
   jobs via payload.project='<slug>'.
   ============================================================ */

// "now" anchor so relative times render deterministically
const NOW = new Date('2026-06-08T21:08:41');

const HOSTS = [
  { id: 'elitedesk', role: 'server',     up: '41d 06:12', lag: 2,  hd: 'good' },
  { id: 'win10', role: 'gpu',        up: '3d 18:44',  lag: 4,  hd: 'good' },
  { id: 'rpi', role: 'monitoring', up: '88d 22:01', lag: 8,  hd: 'good' },
];

/* ---------- projects (vault-derived) ---------- */
const PROJECTS = [
  {
    slug: 'home-ops', title: 'home-ops console', status: 'hot',
    path: '~/vault/projects/home-ops.md', last_commit: '2026-06-08T18:22:00',
    commits_30d: 71, updated_at: '2026-06-08T20:55:00',
    spark: [0,1,0,2,1,3,2,4,3,2,5,4,3,6,4,3,5,7,4,3,2,4,3,5,4,6,3,4,8,5],
    now: [['Chat tab streaming UX', false],['Footer ambient health probes', false],['wire URL fragment router', true],['model picker from gpu_models_loaded', false]],
    next: [['Projects drill writeback', false],['pid correlation in Logs', false],['PWA manifest', false]],
    later: [['saved deep-link chips', false],['inbox triage tab', false]],
    pain: 'Live tail still re-layouts the whole tbody on append at >300 rows. Need keyed row reuse, not innerHTML.',
    errors_today: 0, jobs_q: 1,
  },
  {
    slug: 'guitar-crm', title: 'guitar lesson CRM', status: 'hot',
    path: '~/vault/projects/guitar-crm.md', last_commit: '2026-06-08T15:40:00',
    commits_30d: 58, updated_at: '2026-06-08T16:10:00',
    spark: [3,2,4,1,5,3,6,4,2,5,3,7,4,6,3,5,8,4,3,6,5,4,7,3,5,4,6,5,4,7],
    now: [['Stripe webhook idempotency keys', false],['SMS reminder cron at T-24h', false],['student no-show flagging', true]],
    next: [['invoice PDF templating', false],['calendar 2-way sync', false]],
    later: [['parent portal', false]],
    pain: 'Twilio sandbox rate-limits the reminder batch; need the production A2P number provisioned before launch.',
    errors_today: 3, jobs_q: 0,
  },
  {
    slug: 'stano', title: 'stano — status board', status: 'warm',
    path: '~/vault/projects/stano.md', last_commit: '2026-06-06T11:02:00',
    commits_30d: 22, updated_at: '2026-06-06T11:30:00',
    spark: [0,2,1,3,0,2,1,4,2,1,3,0,2,1,2,3,1,0,2,1,3,2,1,0,2,1,2,0,1,3],
    now: [['debounce the SSE reconnect storm', false],['favicon badge for unread', false]],
    next: [['dark/light auto from system', false]],
    later: [['multi-board support', false]],
    pain: 'SSE reconnect storm when laptop wakes from sleep — backoff is linear, should be exponential w/ jitter.',
    errors_today: 1, jobs_q: 0,
  },
  {
    slug: 'job-search', title: 'job-search tracker', status: 'warm',
    path: '~/vault/projects/job-search.md', last_commit: '2026-06-05T09:14:00',
    commits_30d: 14, updated_at: '2026-06-05T09:40:00',
    spark: [1,0,2,1,0,3,1,2,0,1,2,1,0,2,1,0,1,2,0,1,0,2,1,0,1,0,2,1,0,1],
    now: [['scrape Ashby boards nightly', false],['embed JDs for similarity rank', false]],
    next: [['dedupe by company+title', false]],
    later: [],
    pain: 'Greenhouse changed their DOM; the parser silently returns 0 rows instead of erroring.',
    errors_today: 0, jobs_q: 1,
  },
  {
    slug: 'inbox-zero', title: 'inbox-zero agent', status: 'dormant',
    path: '~/vault/projects/inbox-zero.md', last_commit: '2026-05-19T22:50:00',
    commits_30d: 4, updated_at: '2026-05-19T23:10:00',
    spark: [2,1,0,1,0,0,1,0,0,0,1,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    now: [['retrain the priority classifier', false]],
    next: [['unsubscribe heuristics', false]],
    later: [],
    pain: 'Classifier drifted after the Fastmail folder reshuffle; precision dropped to ~0.6.',
    errors_today: 0, jobs_q: 0,
  },
  {
    slug: 'pixel-pet', title: 'pixel-pet (gba)', status: 'stalled',
    path: '~/vault/projects/pixel-pet.md', last_commit: '2026-04-28T14:05:00',
    commits_30d: 0, updated_at: '2026-04-28T14:30:00',
    spark: [1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    now: [['fix sprite OAM flicker on bank switch', false],['mGBA build broken since toolchain bump', false]],
    next: [['save-state to SRAM', false]],
    later: [],
    pain: 'devkitARM 1.99 broke the linker script; blocked until I find time to chase the symbol map.',
    errors_today: 0, jobs_q: 0,
  },
];

/* ---------- conversations (gpu_jobs as chat) ---------- */
const MODELS_LOADED = [
  { name: 'qwen3:8b', vram: 5.8 },
  { name: 'nomic-embed-text', vram: 0.4 },
];
const MODEL_LIBRARY = [
  'qwen3:8b','qwen3:14b','llama3.2:3b','deepseek-r1:14b','gemma3:12b',
  'mistral-small:24b','codestral:22b','nomic-embed-text','phi4:14b',
];

const CONVERSATIONS = [
  {
    id: 47, title: 'why is the live tail re-layouting', model: 'qwen3:8b',
    project: 'home-ops', updated: '2026-06-08T21:07:55', status: 'running',
    turns: [
      { role: 'user', text: 'The Logs live tail jank — every 2s append triggers a full reflow of the tbody. I\'m rebuilding innerHTML. What\'s the minimal fix that keeps it vanilla, no framework?' },
      { role: 'assistant', status: 'running', model: 'qwen3:8b',
        thinking: 'The user is rebuilding innerHTML on every tick. That forces the browser to re-parse and re-layout the entire table body. Each row is being destroyed and recreated even though 99% are unchanged. The fix is to stop touching existing DOM. I should suggest: (1) keep a ring buffer of row nodes, (2) on new event, create one <tr>, prepend or append it, and remove the oldest node if over cap. This is O(1) DOM mutation per tick. Also mention content-visibility:auto for offscreen rows, and avoid reading layout props (offsetHeight) in the same frame as writes to dodge forced synchronous layout...',
        tokens: 612, elapsed: 14, started: '2026-06-08T21:07:41',
        text: 'Stop rebuilding `innerHTML`. The whole table is being re-parsed every tick even though only one row changed. Three moves:\n\n**1. Mutate, don\'t replace.** Keep the `<tbody>` and only ever `prepend` a single new `<tr>`, then `removeChild` the oldest if you\'re over the row cap. That\'s one node in, one node out — O(1) per tick instead of O(n).\n\n**2. Never read layout in the write path.** If you touch `scrollTop`/`offsetHeight` right after inserting, you force a synchronous reflow. Batch reads' },
    ],
  },
  {
    id: 46, title: 'summarise today\'s guitar-crm errors', model: 'qwen3:8b',
    project: 'guitar-crm', updated: '2026-06-08T20:41:00', status: 'paused',
    turns: [
      { role: 'user', text: '/summarise the 3 error-level events from app:guitar-crm today — what\'s the common cause?' },
      { role: 'assistant', status: 'paused', model: 'qwen3:8b',
        thinking: 'Pulling the three error rows. They share pid 31254 and all reference the Twilio client...',
        tokens: 240, elapsed: 6, started: '2026-06-08T20:40:48', paused_reason: 'gaming on win10 — will resume when GPU idle',
        text: 'All three errors trace back to the Twilio reminder batch hitting the sandbox rate limit (HTTP 429). They share `pid: 31254`. The cron fires 14 SMS in a tight loop at 09:00; the sandbox caps at' },
    ],
  },
  {
    id: 45, title: 'exponential backoff with jitter snippet', model: 'deepseek-r1:14b',
    project: 'stano', updated: '2026-06-08T19:12:00', status: 'done',
    turns: [
      { role: 'user', text: 'Give me a tiny exponential backoff with full jitter for an SSE reconnect. JS, no deps.' },
      { role: 'assistant', status: 'done', model: 'deepseek-r1:14b',
        thinking: 'Full jitter is sleep = random(0, min(cap, base * 2^attempt)). Cap around 30s, base 500ms...',
        tokens: 388, elapsed: 11, started: '2026-06-08T19:11:42',
        text: 'Full-jitter backoff — capped at 30s, base 500ms:\n\n```js\nlet attempt = 0;\nfunction nextDelay() {\n  const cap = 30_000, base = 500;\n  const ceil = Math.min(cap, base * 2 ** attempt++);\n  return Math.random() * ceil;\n}\n```\n\nReset `attempt = 0` on a successful `open`. This kills the reconnect storm on laptop wake — instead of 14 clients all retrying at t+1s, they spread across the window.' },
    ],
  },
  {
    id: 44, title: 'embed Now items for home-ops', model: 'nomic-embed-text',
    project: 'home-ops', updated: '2026-06-08T17:30:00', status: 'done',
    turns: [
      { role: 'user', text: '/embed the 4 Now items so I can similarity-search against past notes' },
      { role: 'assistant', status: 'done', model: 'nomic-embed-text',
        tokens: 0, elapsed: 2, started: '2026-06-08T17:29:58',
        text: 'Embedded 4 items → 4 × 768-dim vectors written to `embeddings`. Closest prior note: "keyed DOM diffing for tail" (cos 0.81).' },
    ],
  },
  {
    id: 43, title: 'greenhouse parser returns 0 rows', model: 'qwen3:14b',
    project: 'job-search', updated: '2026-06-08T11:02:00', status: 'failed',
    turns: [
      { role: 'user', text: 'My greenhouse scraper silently returns 0 rows. How do I make it loud when the selector misses?' },
      { role: 'assistant', status: 'failed', model: 'qwen3:14b',
        tokens: 90, elapsed: 3, started: '2026-06-08T11:01:50', fail_reason: 'ollama: model qwen3:14b not resident — load timed out after 30s',
        text: '' },
    ],
  },
  {
    id: 42, title: 'cancelled — regex for journald units', model: 'qwen3:8b',
    project: null, updated: '2026-06-07T22:14:00', status: 'cancelled',
    turns: [
      { role: 'user', text: 'regex to extract the unit name from journald:<unit> source strings' },
      { role: 'assistant', status: 'cancelled', model: 'qwen3:8b', tokens: 41, elapsed: 1, started: '2026-06-07T22:13:55', text: '' },
    ],
  },
];

/* ---------- logs (host_logs) ---------- */
const LEVELS = ['debug','info','warn','error','fatal'];
function mkLog(t, host, level, source, msg, data) {
  return { ts: t, host, level, source, msg, data: data || {} };
}
// generated-ish dense stream, newest first
const LOGS = [
  mkLog('21:08:39','elitedesk','info','app:home-ops','router resolved #tab=chat&conv=47',{tab:'chat',conv:47,ms:2}),
  mkLog('21:08:38','win10','info','agent:OllamaWatcher','gpu_models_loaded=[qwen3:8b,nomic-embed-text]',{vram_gb:6.2,temp_c:61}),
  mkLog('21:08:37','win10','warn','app:home-ops','job 46 paused: gaming preempt detected',{job:46,fg_proc:'cs2.exe',pid:31254}),
  mkLog('21:08:35','elitedesk','info','docker:cloudflared','conn registered iad07 h2',{conn:'a91f',rtt_ms:11}),
  mkLog('21:08:33','elitedesk','info','app:home-ops','sse client connected',{clients:3,ip:'100.92.x.x'}),
  mkLog('21:08:30','rpi','debug','journald:systemd','host_metrics flush ok',{rows:3,lag_ms:8}),
  mkLog('21:08:22','win10','info','agent:gpu-sampler','sample cpu=22 mem=58 gpu=4',{gpu_pct:4,gpu_temp_c:61}),
  mkLog('21:08:19','elitedesk','info','docker:postgres','checkpoint complete',{buffers:412,wal_mb:6.1}),
  mkLog('21:08:11','elitedesk','error','app:guitar-crm','twilio send failed 429 rate_limited',{pid:31254,to:'+1503xxx"',code:429,batch:14}),
  mkLog('21:08:11','elitedesk','warn','app:guitar-crm','reminder batch retry 2/3',{pid:31254,delay_ms:2400}),
  mkLog('21:07:58','win10','info','agent:OllamaWatcher','load qwen3:8b resident',{vram_gb:5.8,load_ms:1840}),
  mkLog('21:07:41','elitedesk','info','app:home-ops','job 47 enqueued kind=generate',{job:47,project:'home-ops',model:'qwen3:8b'}),
  mkLog('21:07:33','elitedesk','info','docker:cloudflared','GET /api/jobs 200',{ms:14,bytes:8201}),
  mkLog('21:06:50','rpi','info','journald:ssh','accepted publickey for ada',{from:'100.92.x.x',port:54122}),
  mkLog('21:06:12','elitedesk','debug','app:home-ops','health probe ok',{ingest:'ok',q_running:1,q_queued:2}),
  mkLog('21:05:44','elitedesk','warn','app:stano','sse reconnect storm: 9 clients in 1200ms',{pid:8841,clients:9}),
  mkLog('21:04:09','win10','info','docker:ollama','POST /api/generate stream open',{model:'qwen3:8b',job:47}),
  mkLog('21:03:21','elitedesk','info','app:guitar-crm','stripe webhook charge.succeeded',{evt:'evt_3Pq',amt:6000,pid:31254}),
  mkLog('21:02:55','elitedesk','error','app:guitar-crm','twilio send failed 429 rate_limited',{pid:31254,to:'+1971xxx',code:429,batch:14}),
  mkLog('21:01:30','rpi','debug','journald:systemd','cron run reminder-batch start',{unit:'reminder.timer'}),
  mkLog('21:00:02','elitedesk','info','docker:postgres','autovacuum host_logs',{dead:18402,ms:920}),
  mkLog('20:58:41','elitedesk','error','app:guitar-crm','twilio send failed 429 rate_limited',{pid:31254,to:'+1206xxx',code:429,batch:14}),
  mkLog('20:55:10','win10','info','agent:gpu-sampler','sample cpu=18 mem=55 gpu=3',{gpu_pct:3,gpu_temp_c:59}),
  mkLog('20:52:00','elitedesk','info','app:job-search','ashby scrape ok 42 postings',{new:6,dupe:36}),
  mkLog('20:49:13','elitedesk','warn','app:job-search','greenhouse parser returned 0 rows',{board:'acme',selector:'.opening'}),
  mkLog('20:44:22','elitedesk','info','docker:cloudflared','GET /api/projects 200',{ms:31,rows:6}),
  mkLog('20:40:48','win10','warn','app:home-ops','job 46 paused gaming preempt',{job:46,pid:31254}),
  mkLog('20:38:00','rpi','info','journald:systemd','disk usage rpi / 41%',{used_gb:24,total_gb:59}),
  mkLog('20:31:17','elitedesk','debug','app:home-ops','inbox.md appended 1 line',{file:'inbox.md',bytes:62}),
  mkLog('20:22:05','elitedesk','info','docker:postgres','connection from 100.92.x.x',{db:'homeops',backend:31901}),
];

/* ---------- host_metrics (sparkline series + top procs) ---------- */
function series(base, amp, n) {
  const a = []; let v = base;
  for (let i = 0; i < n; i++) { v += (Math.sin(i*0.7)*amp) + (i%4-1.5)*amp*0.4; a.push(Math.max(0, Math.min(100, Math.round(base + (v-base)*0.5 + (i%3)*2)))); }
  return a;
}
const METRICS = {
  elitedesk: {
    cpu: 31, mem: 47, disk: 38, net: '4.1MB/s', gpu: null,
    cpu_s: series(28,18,60), mem_s: series(46,8,60), gpu_s: null,
    lag: 2,
    top_cpu: [['postgres',14.2,31901],['cloudflared',6.1,1102],['node ingest',5.4,2890],['docker-proxy',2.1,1140],['journald',1.0,402]],
    docker: ['postgres','cloudflared','ingest','caddy'],
  },
  win10: {
    cpu: 22, mem: 58, disk: 71, net: '0.9MB/s', gpu: 4, gpu_mem: 38, gpu_temp: 61,
    cpu_s: series(24,22,60), mem_s: series(57,6,60), gpu_s: series(8,30,60),
    lag: 4,
    top_cpu: [['cs2.exe',41.0,31254],['ollama',12.4,8120],['steamwebhelper',8.8,7740],['gpu-sampler',1.2,8990],['OllamaWatcher',0.9,9012]],
    docker: ['ollama'], gpu_models: [['qwen3:8b',5.8],['nomic-embed-text',0.4]],
  },
  rpi: {
    cpu: 9, mem: 34, disk: 41, net: '0.2MB/s', gpu: null,
    cpu_s: series(8,6,60), mem_s: series(33,4,60), gpu_s: null,
    lag: 8,
    top_cpu: [['python sampler',3.1,8841],['systemd-journald',1.4,221],['promtail',1.1,640],['sshd',0.4,541],['node_exporter',0.3,712]],
    docker: [],
  },
};

const HEALTH = { ingest: 'ok', q_running: 1, q_queued: 2 };

window.DB = { NOW, HOSTS, PROJECTS, CONVERSATIONS, MODELS_LOADED, MODEL_LIBRARY, LOGS, LEVELS, METRICS, HEALTH };
