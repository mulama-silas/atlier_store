import 'dotenv/config';
import { z } from 'zod';

const configSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  APP_URL: z.string().url().default('http://127.0.0.1:3000'),
  SUPABASE_URL: z.string().url().optional(),
  SUPABASE_ANON_KEY: z.string().min(1).optional(),
  SUPABASE_SERVICE_ROLE_KEY: z.string().min(1).optional(),
  MPESA_CONSUMER_KEY: z.string().min(1).optional(),
  MPESA_CONSUMER_SECRET: z.string().min(1).optional(),
  MPESA_SHORTCODE: z.string().min(1).optional(),
  MPESA_PASSKEY: z.string().min(1).optional(),
  MPESA_CALLBACK_URL: z.string().url().optional(),
  MPESA_CALLBACK_SECRET: z.string().min(16).default('modeza_mpesa_callback_2026'),
  MPESA_ENV: z.enum(['sandbox', 'production']).default('sandbox'),
  PAYMENT_WEBHOOK_SECRET: z.string().min(16).default('modeza_webhook_secret_2026'),
  SESSION_SECRET: z.string().min(16).default('modeza_session_secret_2026'),
  ADMIN_API_TOKEN: z.string().min(16).optional(),
  // Development only: location of the Django SQLite database and the origin the
  // Django dev server serves /media files from.
  DJANGO_SQLITE_PATH: z.string().min(1).optional(),
  DJANGO_BASE_URL: z.string().url().default('http://localhost:8000'),
});

const parsedConfig = configSchema.safeParse(process.env);

if (!parsedConfig.success) {
  const issues = parsedConfig.error.issues
    .map((issue) => `${issue.path.join('.')}: ${issue.message}`)
    .join(', ');
  throw new Error(`Invalid environment configuration: ${issues}`);
}

const config = parsedConfig.data;

if (config.NODE_ENV === 'production') {
  const devDefaults: Array<[string, string]> = [
    ['SESSION_SECRET', 'modeza_session_secret_2026'],
    ['PAYMENT_WEBHOOK_SECRET', 'modeza_webhook_secret_2026'],
    ['MPESA_CALLBACK_SECRET', 'modeza_mpesa_callback_2026'],
  ];
  for (const [key, value] of devDefaults) {
    if ((config as Record<string, string>)[key] === value) {
      throw new Error(
        `Invalid environment configuration: ${key} must be set to a strong, unique value in production.`
      );
    }
  }
  if (!process.env.SUPABASE_URL || !process.env.SUPABASE_SERVICE_ROLE_KEY) {
    throw new Error(
      'Invalid environment configuration: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required in production.'
    );
  }
}

export { config };

export const isSupabaseConfigured = Boolean(
  config.SUPABASE_URL && config.SUPABASE_SERVICE_ROLE_KEY
);

export function requireSupabaseConfig(): {
  url: string;
  serviceRoleKey: string;
} {
  if (!isSupabaseConfigured) {
    throw new Error(
      'Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY before using persistent storage.'
    );
  }

  return {
    url: config.SUPABASE_URL!,
    serviceRoleKey: config.SUPABASE_SERVICE_ROLE_KEY!,
  };
}
