---
name: frontend-aesthetics-distilled
description: Distinctive, non-generic visual direction for frontend work — HTML pages, React components, landing pages, dashboards, mockups, and any UI Claude builds. Use this whenever creating or redesigning a frontend, even if the user only asks for a page or component and doesn't mention design explicitly. Counters the default "AI slop" aesthetic (Inter/Roboto/system fonts, purple gradients on white, predictable layouts) by pushing for a specific, cohesive, context-driven aesthetic instead.
---

# Frontend aesthetics: avoid the generic default

Claude tends to converge toward generic, "on distribution" outputs. In frontend design, this creates what users call the "AI slop" aesthetic. Avoid this: make creative, distinctive frontends that surprise and delight.

## Typography

Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial and Inter; opt instead for distinctive choices that elevate the frontend's aesthetics.

## Color and theme

Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly distributed palettes. Draw from IDE themes and cultural aesthetics for inspiration.

## Motion

Use animations for effects and micro-interactions. Prioritize CSS-only solutions for HTML. Use the Motion library for React when available. Focus on high-impact moments: one well-orchestrated page load with staggered reveals (`animation-delay`) creates more delight than scattered micro-interactions.

## Backgrounds

Create atmosphere and depth rather than defaulting to solid colors. Layer CSS gradients, use geometric patterns, or add contextual effects that match the overall aesthetic.

## Avoid generic AI-generated aesthetics

- Overused font families (Inter, Roboto, Arial, system fonts)
- Clichéd color schemes, particularly purple gradients on white backgrounds
- Predictable layouts and component patterns
- Cookie-cutter design that lacks context-specific character

## Stay unpredictable across generations

Interpret creatively and make unexpected choices that feel genuinely designed for the context. Vary between light and dark themes, different fonts, and different aesthetics from one build to the next. There's still a tendency to converge on the same "safe" distinctive choices (Space Grotesk, for example) across generations — actively resist that. It's critical to think outside the box each time, not just once.
