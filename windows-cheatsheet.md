# Windows / PowerShell Tool Cheat Sheet

The `bash` tool in Windsurf on this machine is PowerShell, not bash/sh. Avoid Unix-only commands.

## Use IDE tools instead

- Show a file: use `read_file` tool, not `cat`.
- Search code: use `grep_search` tool, not `grep`.
- Find files: use `find_by_name` tool, not `find`.
- Read command output: use `command_status` with a small `OutputCharacterCount`.

## PowerShell equivalents

| Unix | PowerShell |
|------|------------|
| `head -n 10` | `Select-Object -First 10` |
| `tail -n 10` | `Select-Object -Last 10` |
| `grep pattern` | `Select-String pattern` |
| `cat file` | `Get-Content file` |
| `mkdir -p dir` | `New-Item -ItemType Directory -Force dir` |
| `rm file` | `Remove-Item file` |
| `mv src dst` | `Move-Item src dst` |
| `cp src dst` | `Copy-Item src dst` |

## Important rules

- Never use `cd` in a `bash` command. Use the `Cwd` parameter.
- Quote paths that contain spaces.
- Keep `read_file` calls under 1000 lines; use `offset`/`limit` for large files.
- Limit parallel tool calls to a few unrelated ones.
- Avoid generating huge responses; split large edits.
