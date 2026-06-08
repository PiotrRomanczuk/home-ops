import { serve } from '@hono/node-server';
import { Hono } from 'hono';
import { logger } from 'hono/logger';
import { env } from './env.ts';
import { registerAuthRoutes } from './routes/auth.ts';
import { registerHealthRoutes } from './routes/health.ts';
import { registerIngestRoutes } from './routes/ingest.ts';
import { registerJobsRoutes } from './routes/jobs.ts';
import { registerLogsRoutes } from './routes/logs.ts';
import { registerMetricsRoutes } from './routes/metrics.ts';
import { registerProjectsRoutes } from './routes/projects.ts';

const app = new Hono();
app.use('*', logger());

// Order matters: auth middlewares inside each register* are positional. Health
// is unauthenticated and registered first so /api/health stays out of any
// future global guard. Auth routes (login/logout + viewer pages) come last so
// the static `/` handler is the catch-all rather than shadowing anything above.
registerHealthRoutes(app);
registerIngestRoutes(app);
registerMetricsRoutes(app);
registerLogsRoutes(app);
registerJobsRoutes(app);
registerProjectsRoutes(app);
registerAuthRoutes(app);

serve({ fetch: app.fetch, port: env.PORT }, (info) => {
  console.log(`home-ops listening on :${info.port}`);
});
