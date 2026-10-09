// Opt-in pilot GA4 test. No company property; no real enquiry data.
(() => {
  'use strict';
  const enabled = new URLSearchParams(location.search).get('telemetry') === 'ga4-test';
  const measurement = 'G-EP0Y94K2B6';
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
    content_version: 'headline-2026-10-09-v1', data_kind: 'synthetic', debug_mode: true};
  const original = window.gtag;
  window.gtag = function(command, name, params) {
    if (command === 'event') {
      params = Object.assign({}, params || {}, metadata);
      return original(command, 'pilot_' + name, params);
    }
    return original.apply(this, arguments);
  };
  function expose() {
    document.querySelector('.hero > h1').textContent = variant === 'control' ?
      'Connect your operations. See your business clearly.' :
      'Find the gaps between your business systems.';
    const label = document.createElement('p');
    label.textContent = 'Synthetic headline experiment: ' + variant + (enabled ? '. Pilot GA4 test enabled.' : '. External tracking is blocked.');
    label.id = 'experiment-status';
    document.querySelector('.hero').appendChild(label);
    window.gtag('event', 'experiment_exposure', metadata);
  }
  if (enabled) {
    window['ga-disable-' + measurement] = false;
    gtag('set', Object.assign({}, metadata, {page_location: location.origin + location.pathname, page_referrer: ''}));
    const loader = document.createElement('script');
    loader.async = true;
    loader.src = 'https://www.googletagmanager.com/gtag/js?id=' + measurement;
    document.head.appendChild(loader);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', expose, {once:true});
  else expose();
})();
