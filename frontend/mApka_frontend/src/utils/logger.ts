// src/utils/logger.ts
// Nasze kolorowe "pieczątki" do konsoli – od razu widać, kto mówi.

const tag = (name: string, _color: string) =>
  `%c[${name}]%c`; // %c = miejsce, w którym działa styl CSS

const style = (color: string) => `color:${color};font-weight:bold`;
const reset = 'color:inherit';

export const logger = {
  api: (msg: string, data?: unknown) =>
    console.log(tag('API', '#2563eb'), style('#2563eb'), reset, msg, data ?? ''),
  store: (msg: string, data?: unknown) =>
    console.log(tag('STORE', '#16a34a'), style('#16a34a'), reset, msg, data ?? ''),
  map: (msg: string, data?: unknown) =>
    console.log(tag('MAP', '#f59e0b'), style('#f59e0b'), reset, msg, data ?? ''),
  warn: (msg: string, data?: unknown) =>
    console.warn('[WARN]', msg, data ?? ''),
  error: (msg: string, data?: unknown) =>
    console.error('[ERROR]', msg, data ?? ''),
};