---
name: claude-settings-split
description: >-
  Move uncommitted changes from shared claude/.claude/settings.json to profiles/claude_personal.json, claude_work.json, or claude_homelab.json. Use for profile-specific hooks, plugins, permissions, or absolute paths.
---

# Claude Settings Split

Base `claude/.claude/settings.json` must remain profile-neutral. Machine-specific configs belong in `profiles/claude_personal.json`, `profiles/claude_work.json`, or `profiles/claude_homelab.json`.
Mergeable keys (`hooks`, `enabledPlugins`, `permissions`) combine automatically across base and profile settings.

## Procedure

1. **Target**: Ask user if target is `personal`, `work`, or `homelab` (don't guess).
2. **Diff**: Check `git diff` and `git diff --staged` for `claude/.claude/settings.json`. Identify what moves vs. what stays.
3. **Merge**: Edit `profiles/claude_<target>.json` (treat `{}` as valid base). Copy fragments verbatim:
   - **`hooks.<Event>`**: Append new blocks to the array. Do not overwrite existing entries.
   - **`enabledPlugins`**: Add new keys. Leave existing alone.
   - **`permissions` / scalars**: Set key. If conflict exists, ask user.
   - **Changed existing keys**: Ask user (not a pure additive move).
4. **Clean Base**:
   - Entire diff moving: `git checkout -- claude/.claude/settings.json`
   - Partial move: Manually remove the moved fragment (reference `git show HEAD:claude/.claude/settings.json`).
5. **Validate**:
   ```bash
   python3 -m json.tool claude/.claude/settings.json >/dev/null
   python3 -m json.tool profiles/claude_<target>.json >/dev/null
   ```
6. **Show Results**: Run `git diff` on both files.

## Gotchas

- **Paths**: Rewrite hardcoded `/home/<user>/...` to `"$HOME/..."` (requires double quotes for expansion).
- **Git**: Leave results unstaged. Never commit unless explicitly asked.
- **Stow**: No need to re-run stow (files are stowed folded).
