// Shared app state — one object, imported by every module.
export const state = {
  source: null, // "opencode" | "cursor" | "claude" | null (home)
  account: "default", // claude account id (a CLAUDE_CONFIG_DIR); "default" = ~/.claude
  sessions: [],
  projects: [],
  models: [],
  selectedId: null,
  detail: null,
  selected: new Set(),
  selectAnchor: null, // id of the last clicked row, for shift-click range select
  collapsedProjects: new Set(), // project keys whose group is collapsed
  projectFilter: "", // project id the list is filtered to ("" = all projects)
  showArchived: false, // include archived sessions in the list
};
