// Local synthetic preview only. Deployment requires a separate reviewed script release.
(() => {
  'use strict';
  const id = 'workflow_headline_v1';
  const key = 'prymage.synthetic.' + id;
  const forced = new URLSearchParams(location.search).get('variant');
  let variant;
  try {
    variant = sessionStorage.getItem(key);
    if (!['control', 'assessment'].includes(variant)) {
      variant = ['control', 'assessment'].includes(forced) ? forced :
        (crypto.getRandomValues(new Uint32Array(1))[0] % 2 ? 'assessment' : 'control');
      sessionStorage.setItem(key, variant);
    }
  } catch (_) {
    variant = ['control', 'assessment'].includes(forced) ? forced : 'assessment';
  }
  const metadata = {experiment_id: id, experiment_variant: variant,
    content_version: 'headline-2026-10-09-v1', data_kind: 'synthetic'};
  const original = window.gtag;
  window.gtag = function(command, name, params) {
    if (command === 'event') {
      params = Object.assign({}, params || {}, metadata);
      return original(command, name, params);
    }
    return original.apply(this, arguments);
  };
  function expose() {
    document.querySelector('.hero > h1').textContent = variant === 'control' ?
      'Connect your operations. See your business clearly.' :
      'Find the gaps between your business systems.';
    const label = document.createElement('p');
    label.textContent = 'Synthetic headline experiment: ' + variant + '. External tracking is blocked.';
    label.id = 'experiment-status';
    document.querySelector('.hero').appendChild(label);
    window.gtag('event', 'experiment_exposure', metadata);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', expose, {once:true});
  else expose();
})();
