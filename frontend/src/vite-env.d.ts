/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_ADMIN_URL?: string;
  readonly VITE_DEFAULT_WHATSAPP_NUMBER?: string;
  readonly VITE_SUPPORT_EMAIL?: string;
  readonly VITE_USE_DUMMYJSON?: string;
  readonly VITE_DUMMYJSON_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
