import { Container } from '@cloudflare/containers';
import { DurableObject } from 'cloudflare:workers';
import { handleBudgetedInference } from './ai-gateway.js';

export class TutorAIBudget extends DurableObject {
  async fetch(request) {
    return handleBudgetedInference(request, this.env, this.ctx.storage);
  }
}

export class LinguaPathContainer extends Container {
  defaultPort = 8000;
  sleepAfter = '5m';
  envVars = {
    DJANGO_DEBUG: 'false',
    DJANGO_SECRET_KEY: this.env.DJANGO_SECRET_KEY,
    DATABASE_URL: this.env.DATABASE_URL,
    DJANGO_ALLOWED_HOSTS: this.env.DJANGO_ALLOWED_HOSTS,
    DJANGO_CSRF_TRUSTED_ORIGINS: this.env.DJANGO_CSRF_TRUSTED_ORIGINS,
    DJANGO_TRUST_PROXY_SSL_HEADER: 'true',
    DJANGO_AUTH_TRUSTED_PROXIES: this.env.DJANGO_AUTH_TRUSTED_PROXIES || '',
    DJANGO_AUTH_CLIENT_IP_HEADER: this.env.DJANGO_AUTH_CLIENT_IP_HEADER || '',
    DJANGO_SECURE_HSTS_SECONDS: this.env.DJANGO_SECURE_HSTS_SECONDS || '0',
    AI_TUTOR_ENABLED: this.env.AI_TUTOR_ENABLED || 'false',
    AI_TUTOR_PROVIDER: 'cloudflare',
    CLOUDFLARE_AI_ENDPOINT: this.env.CLOUDFLARE_AI_ENDPOINT || '',
    AI_BRIDGE_SECRET: this.env.AI_BRIDGE_SECRET || '',
    AI_TUTOR_DAILY_LIMIT: this.env.AI_TUTOR_DAILY_LIMIT || '20',
    AI_TUTOR_MINUTE_LIMIT: this.env.AI_TUTOR_MINUTE_LIMIT || '3',
    AI_TUTOR_GLOBAL_DAILY_LIMIT: this.env.AI_TUTOR_GLOBAL_DAILY_LIMIT || '200',
    AI_TUTOR_GLOBAL_MINUTE_LIMIT: this.env.AI_TUTOR_GLOBAL_MINUTE_LIMIT || '20',
    WEB_CONCURRENCY: '1',
  };
}

export { default } from './router.js';
