# RC Visual Checklist (Dashboard)

## Scope
- Screen: `GET /dashboard`
- Themes/presets: `Утро`, `Работа`, `Вечер`, `Неделя`, `Все панели`
- Devices: desktop 1440+, laptop 1280, tablet 1024/820

## 1) Frame and Top Bar
- [ ] Header is compact; title does not wrap unexpectedly.
- [ ] `Параметры` dropdown opens above all panels and is clickable.
- [ ] Status pills render readable text without mojibake.
- [ ] `security` pill updates after `/ops/services` refresh.

## 2) Card System
- [ ] Card borders/headers/meta/tool buttons use one visual style.
- [ ] Card hover state is subtle and consistent.
- [ ] Refresh/expand/pin tool buttons are aligned and clickable.
- [ ] Expanded cards return to normal state without layout break.

## 3) Layout UX
- [ ] `Редактировать` toggles drag mode on/off.
- [ ] `Сохранить` appears enabled only when layout is dirty.
- [ ] `Сброс` restores preset layout.
- [ ] `+ панель` picker opens/closes correctly and adds hidden panels.

## 4) World Clock
- [ ] Add city button works; new city appears immediately.
- [ ] Remove city works from row action.
- [ ] Progress bars and time values align visually.
- [ ] Reset button returns default city list.

## 5) Copilot/Chat
- [ ] Chat panel style matches cards (same dark/green language).
- [ ] User/assistant message bubbles are distinguishable.
- [ ] Action feedback is standardized (ℹ️/✅/⚠️/❌).

## 6) News/Signals Density
- [ ] News titles clamp to 2 lines and remain readable.
- [ ] Source/meta line truncates without wrapping chaos.
- [ ] Links stay clickable and high-contrast.

## 7) Ops and Reliability
- [ ] Restart/reload buttons cannot be spam-clicked concurrently.
- [ ] Loading state appears during dashboard refresh.
- [ ] No UI dead zones after repeated refreshes.

## 8) Encoding and Text
- [ ] No mojibake fragments in UI (`Р...`, `вЂ...`, `рџ...`).
- [ ] Russian labels render correctly in all visible controls.

## 9) Screenshot Set for RC
- [ ] Full dashboard (desktop, work preset)
- [ ] Top bar + status + parameters dropdown
- [ ] World Clock panel (with custom city)
- [ ] Ops panel (security visible)
- [ ] Tablet layout (1024 width)
