/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Origin of the FastAPI backend in production. Unset in dev → Vite proxies /api. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
