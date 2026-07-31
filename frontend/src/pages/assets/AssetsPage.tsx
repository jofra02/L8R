// The assets route renders the tabbed workspace; the master list itself
// lives in AssetListPanel. Kept as a re-export so App.tsx routes and any
// other imports of AssetsPage stay unchanged.
export { AssetsWorkspace as AssetsPage } from "./AssetsWorkspace";
