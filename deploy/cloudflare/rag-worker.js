import { DurableObject } from 'cloudflare:workers';
import { handleRag, reserve } from './rag-runtime.js';

// Coordination atom is the shared usage budget; inference runs outside the DO.
export class RagBudget extends DurableObject {
  async reserve(kind, ids) { return reserve(this.ctx.storage, kind, ids); }
}
export default {fetch:handleRag};
