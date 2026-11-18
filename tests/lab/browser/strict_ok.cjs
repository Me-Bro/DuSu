'use strict';
/* Preloaded with `node --require` (see gc_strict.sh): makes the harness's T.ok accept the (message, condition[, detail]) order that tests/grammar/browser/real.spec.cjs uses.
   The harness's own order is (condition, message), so those 37 calls pass VACUOUSLY (the message string is the "condition") - this file lets that spec be run with its assertions live,
   without editing it. */
const h = require('/repo/tests/resume_interview/browser/harness.cjs');
const orig = h.makeT;
h.makeT = name => {
  const T = orig(name), ok = T.ok.bind(T);
  T.ok = (a, b, c) => (typeof a === 'string' && typeof b !== 'string') ? ok(b, a + (c ? '  ' + String(c).slice(0, 220) : '')) : ok(a, b);
  return T;
};
