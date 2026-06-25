# VantageLife Design Conventions

**Archetype: The Performance Pro** — a dark trading-terminal aesthetic for a real-time sales-tracking mobile app.

## Wrapping and Setup

No JS component bundle is uploaded. All styling comes from CSS custom properties in `styles.css`. Import it in every design:

```html
<link rel="stylesheet" href="styles.css">
```

The body background is `#0D0D0D` (true dark). Always design on this background — the system has no light mode.

## Styling Idiom

**Use CSS custom properties from `styles.css`.** No Tailwind. No inline style attributes. Class utilities are provided for the most common patterns:

| Concern | Classes |
|---|---|
| Colors | `.text-primary` `.text-dim` `.text-muted` `.text-success` `.text-warning` `.text-error` `.text-gold` |
| Surfaces | `.bg-background` `.bg-surface-1` `.bg-surface-2` `.bg-primary` |
| Typography | `.text-display` `.text-h1` `.text-h2` `.text-h3` `.text-body-lg` `.text-body` `.text-body-sm` `.text-label` `.text-metric` |
| Font families | `.font-heading` (Barlow Condensed, uppercase) `.font-mono` (JetBrains Mono, tabular) |
| Components | `.card` `.stat-card` `.btn-primary` `.btn-secondary` `.input` `.ticker` `.gate-banner` `.tab-bar` `.tab-bar__item` `.tab-bar__item--active` |

For custom values, use the CSS variables directly: `var(--color-primary)`, `var(--space-lg)`, etc. Full token list is in `styles.css`.

## Key Tokens to Know

- **Primary green**: `var(--color-primary)` = `#319842` — use for positive metrics, active states, CTAs
- **Border**: `var(--color-border)` = `rgba(255,255,255,0.08)` — use on ALL cards and inputs
- **Surface**: `var(--color-surface-1)` = `#141414` — default card background
- **Metric text**: `var(--text-metric)` = 22px, weight 900, mono font
- **Label text**: `var(--text-label)` = 10px, weight 700, UPPERCASE, 1.4px tracking

## Where the Truth Lives

Read `styles.css` for all token values and class names before styling. Read `guidelines/design-system.md` for typography scale, spacing scale, animation timing, and shadow levels. Read `guidelines/component-specs.md` for exact props, dimensions, and state tables per component.

## Idiomatic Build Snippet

```html
<!-- Stat card — the primary metric display unit -->
<div class="stat-card stat-card--accent-green">
  <span class="stat-card__label">Sales</span>
  <span class="stat-card__value">47</span>
  <span class="stat-card__sub">vs 39 last week</span>
  <div class="stat-card__delta stat-card__delta--positive">
    ↑ +20.5% vs yest.
  </div>
</div>

<!-- Layout glue — dense mobile grid -->
<div style="display:grid; grid-template-columns:1fr 1fr; gap:var(--space-md); padding:var(--space-xl); background:var(--color-background);">
  <!-- stat cards here -->
</div>
```

## Domain Vocabulary

| Term | Meaning |
|---|---|
| Gate Banner | Warning/locked strip at 9 PM (yellow `--color-warning`) and 6 AM lock (red `--color-error`) |
| Midnight Miracle | Entry window before midnight gate — gold accent `--color-gold` |
| Stat Card | Label + large metric number + delta arrow — the core data unit |
| Ticker | Bottom marquee strip in monospace primary green |
| Platinum Wall | Top-performers leaderboard with gold top-border accent |
| Office Tabs | Full-width tab bar; active tab = 2px bottom border in `--color-primary` |
| Close Rate | Sales ÷ (Sits − N1); N1 is never included in any aggregate |
