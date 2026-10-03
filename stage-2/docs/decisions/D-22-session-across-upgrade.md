# D-22 session across upgrade

**Question.** How does a browser signed in before a stage-1→stage-2 export/import stay signed in, given stage 1 §10 'Import removes all previous destination data and credentials'?

**What the specification says.** "A browser signed in before that export/import upgrade must remain signed in afterwards." Stage 1 had no UI, so the browser's session may have been issued by the stage-2 service before the import.

**Choice.** OPEN, escalated to lead. Recommended: (1) the browser keeps the bearer token client-side (localStorage) and every token in an export survives import (stage-1 R-10.11). (2) When the imported state is a stage-1-format state (an upgrade), the stage-2 import additionally keeps destination tokens whose user id exists in the imported state with the same email (case-insensitive) and handle; a stage-2-format import stays pure replacement (R-10.16 unchanged). This satisfies the stage-2 addition without weakening stage-1 replacement semantics for same-version imports.

**Effect on acceptance tests.** ui_upgrade tests cover both: token minted by the stage-1 service and placed in the browser; and browser signed in on stage 2 before the upgrade import.
