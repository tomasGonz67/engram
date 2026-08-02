# Masi Memory Frontend

React + Vite chat interface for Masi Memory. See the repo root's `techStack.md` for why React + Vite (not Next.js), and `DEVELOPMENT.md` for how to run it.

## Structure

Everything lives in one file — `src/App.tsx`. No separate component files for the chat panel, analytics panel, or modals.

This is deliberate, not an oversight. The app itself is genuinely simple — a chat interface, an analytics side panel, a couple of static info modals — and splitting that into a full component architecture (separate files, prop drilling or context, shared state management) would add structure this project doesn't need yet. One file that's easy to read top to bottom beats a folder of components for something this size. Matches the same reasoning already used for the backend: structure expands as complexity actually justifies it, not before. If this file ever gets genuinely hard to navigate, that's the point to split it — not now.
