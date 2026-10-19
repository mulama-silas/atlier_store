import path from 'path';
import { createServer as createViteServer } from 'vite';
import { createExpressApp } from './src/server/app';
import { hydrateFromDjangoSqlite } from './src/server/db/djangoSqlite';

const PORT = Number(process.env.PORT) || 3000;

async function startServer() {
  // Development only (no-op in production): hydrate catalog, orders and stock
  // reservations from the Django backend's SQLite database.
  hydrateFromDjangoSqlite();

  const app = createExpressApp();

  // Vite middleware setup for development or static serving for production
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(path.posix.join('/', 'assets'), (req, res, next) => next()); // pass to static
    app.use((req, res, next) => {
      // If request doesn't match API, serve static or fallback to index.html
      if (req.path.startsWith('/api')) {
        return next();
      }
      next();
    });
    const express = await import('express');
    app.use(express.default.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Boutique API & Storefront server running on http://0.0.0.0:${PORT}`);
  });
}

startServer().catch((err) => {
  console.error('Failed to start server:', err);
  process.exit(1);
});
