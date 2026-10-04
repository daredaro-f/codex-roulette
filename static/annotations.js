// Optional DevDay annotation integration. Ordinary browsers keep the full app.
const annotation = document.oai?.annotation;
const cards = ['feature-card', 'topic-card', 'constraint-card']
  .map((id) => document.getElementById(id)).filter(Boolean);

if (cards.length) {
  const container = cards[0].parentElement;
  container.setAttribute('oai-annotation-container', '');
  const labels = ['実験に使う新機能', '実験のお題', '実験の変な制約'];
  cards.forEach((card, index) => card.setAttribute('oai-annotatable', labels[index]));

  window.addEventListener('roulette:result', (event) => {
    const result = event.detail;
    const metadata = {
      featureId: result.feature_id,
      topic: result.topic,
      constraint: result.constraint,
      source: result.source,
      verifiedAt: result.feature.verified_at,
    };
    cards.forEach((card) => card.setAttribute('oai-annotation-metadata', JSON.stringify(metadata)));
  });

  let registration;
  const root = document.documentElement;
  const baseline = getComputedStyle(root).getPropertyValue('--accent-cyan').trim();
  if (typeof annotation?.registerControls === 'function' && /^#[\da-f]{3,8}$/i.test(baseline)) {
    try {
      registration = annotation.registerControls({
        targets: [cards[0]],
        controlsHeading: 'ネオンのアクセントを試す',
        controlsMode: 'extend',
        controls: [{
          type: 'color', label: '機能カードのアクセント',
          callback: 'setFeatureAccent', reference: '--accent-cyan', currentValue: baseline,
        }],
      });
      cards[0].addEventListener('oaiannotationcontrolchange', (event) => {
        const { callback, value } = event.detail;
        if (callback === 'setFeatureAccent' && /^#[\da-f]{3,8}$/i.test(value)) {
          root.style.setProperty('--accent-cyan', value);
        }
      });
    } catch {
      // A client without these controls can still use normal annotations.
    }
  }

  const button = document.getElementById('annotation-button');
  if (button && typeof annotation?.request === 'function') {
    button.hidden = false;
    button.addEventListener('click', () => {
      try {
        const accepted = annotation.request(cards[0], {
          mode: 'advanced',
          initialComment: 'この実験カードのアクセントを調整して、変更をコードへ反映して。',
        }).accepted;
        if (!accepted) {
          button.textContent = '注釈モードからカードを選んでね';
        }
      } catch {
        button.textContent = 'ブラウザの注釈モードから選んでね';
      }
    });
  }
  window.addEventListener('pagehide', () => registration?.dispose(), { once: true });
}
